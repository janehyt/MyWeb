# -*- coding: UTF-8 -*- 
from django.shortcuts import get_object_or_404

# Create your views here.
from django.contrib.auth.models import User
from django.contrib import auth
from collections import OrderedDict
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.parsers import FileUploadParser,MultiPartParser
from rest_framework.decorators import permission_classes,detail_route,list_route
from rest_framework.permissions import AllowAny,IsAuthenticated
from .serializers import UserSerializer,ContainerSerializer,ImageSerializer,ProgressSerializer
from .docker_client import DockerClient,DockerHub
from .models import Container,Image,Progress
from api import files
from docker import errors
from mysite import settings
import os,json,markdown,time
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 1000


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer
    pagination_class = StandardResultsSetPagination

    @list_route(methods=['POST'],permission_classes=[AllowAny,])
    def sign_in(self, request):
        data = request.data
        # print(data)
        user = auth.authenticate(username=data['username'],password = data['password'])
        if user and user.is_active:
            auth.login(request,user)
            serializer = self.get_serializer(user)
            return Response(serializer.data)

        return Response("用户名或密码错误",status=404)

    @list_route(methods=['POST'],permission_classes=[AllowAny,])
    def sign_up(self, request):
        data = request.data
        username = data['username']
        email = data['email']
        password = data['password']
        nameFilter = User.objects.filter(username=username)
        emailFilter = User.objects.filter(email=email)
        if(nameFilter):
            return Response("用户名已存在",status=406)
        if(emailFilter):
            return Response("邮箱已注册",status=406)

        # 创建用户
        newUser = User(**data)
        newUser.set_password(password)
        newUser.save()
        # 登陆
        user = auth.authenticate(username=username,password = password)
        if user and user.is_active:
            auth.login(request,user)
            serializer = self.get_serializer(user)
            return Response(serializer.data)

        return Response("验证出错",status=404)

    @list_route()
    def log_out(self, request):
        auth.logout(request)
        return Response("ok")

    @list_route()
    def get_user(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    # @permission_classes(IsAuthenticated)
    # def list(self,request):
    #     pass
class ContainerViewSet(viewsets.ViewSet):

    queryset = Container.objects.all().order_by('-created')
    serializer_class = ContainerSerializer
    pagination_class = StandardResultsSetPagination

    def list(self, request):
        base_url = "http://"+request.get_host()+request.path
        pagination = self.pagination_class()

        queryset = Container.objects.filter(user=request.user)

        data = pagination.paginate_queryset(queryset,request)
        
        serializer = ContainerSerializer(data,many=True,context={'request': request})
        containers = serializer.data
        cli = DockerClient().getClient()
        for container in containers:
            try:
                c = cli.inspect_container(container["name"])["State"]
            except errors.NotFound:
                container["state"] = {"Status":"ghost"}
            else:
                container["state"] = c
                container["url"] = base_url+str(container['id'])
        return pagination.get_paginated_response(containers)

    def retrieve(self, request, pk=None):
        # queryset = Container.objects.all()
        data = get_object_or_404(self.queryset, pk=pk,user=request.user)
        # print self.get_serializer(data).data
        cli = DockerClient().getClient()
        try:
            container = cli.inspect_container(data.name)
        except errors.NotFound:
            return Response({"detail":"Not found."},status=404)
        else: 
            container['url'] = "http://"+request.get_host()+request.path
            return Response(container)

    # def update(self,request,pk=None):
    #     return Response({"detail":"PUT method forbidden"},status=403)
    
    def destroy(self,request,pk=None):
        data = get_object_or_404(self.queryset, pk=pk,user=request.user)
        cli = DockerClient().getClient()
        try:
            cli.remove_container(data.name)
            
        except errors.APIError,e:
            if e.response.status_code==404:
                pass
            else:
                return Response({"reason":e.response.reason,
                    "detail":e.explanation},status=e.response.status_code)
        v_dir = files.getUploadDir(str(request.user))
        v_dir = os.path.join(v_dir,data.name)
        data.delete()
        files.removeDirs(v_dir)

        
        return Response(ContainerSerializer(data).data)

    def create(self,request):
        data = request.data
        nameFilter = Container.objects.filter(name=data.get('name'))     
        # if nameFilter:
        #     return Response("容器名已存在",status=406)
        user = request.user
        data['user'] = user.id
        if data.get('volumes'):
            data['volumes'] = files.resolveVolumes(volumes=data.get('volumes'),path=str(user),name=data.get('name'))
        serializer = ContainerSerializer(data=data)
        if serializer.is_valid():
            print "ok"
            valid_data = serializer.data
            valid_data['user'] = user
            repo = valid_data.get('image')
            if repo:
                repos = repo.split(":")
                image_name = repos[0]
                image_tag = "latest"
                if len(repos)==2:
                    image_tag = repos[1]
                image = Image.objects.get_or_create(name=image_name,tag=image_tag)[0]
                users =  image.users.filter(pk=user.id)
                if user not in users:
                    add = image.users.add(user)
                # image_user=image.users.filter(pk=user.id)
                # print image_user
                valid_data['image']=image
                container = Container(**valid_data)
                container.save()
                data={"id":container.id,"to_pull":container.to_pull()}
                res = Response(data)
        else:
            res = Response(serializer.errors,status=406)
        return res
    @list_route()
    def names(self,request):
        queryset = Container.objects.filter(user=request.user)
        data=[]
        for c in queryset:
            data.append(c.name)
        return Response(data)

    @detail_route()
    def progress(self,request,pk=None):
        container = get_object_or_404(self.queryset, pk=pk,user=request.user)
        cli = DockerClient().getClient()
        # data = self.get_serializer(container).data
        # data = "To Run"
        if container.is_pulling():
            image = container.image
            progresses = image.progresses.all()
            serializer = ProgressSerializer(progresses,many=True)
            return Response(serializer.data)
        return Response("OK")
    @detail_route()
    def pull_image(self,request,pk=None):
        container = get_object_or_404(self.queryset, pk=pk,user=request.user)
        cli = DockerClient().getClient()
        # data = self.get_serializer(container).data
        # data = "To Run"
        print "pull"
        if container.to_pull() or container.is_pulling():
            image = container.image
            pull_image = cli.pull(str(image),stream=True)
            image.status = Image.PULLING
            image.save()
            for line in pull_image:
                pr = json.loads(line)
                status = pr.get("status")
                p_id=pr.get("id","")
                if "Pulling from" not in status and len(p_id)==12:
                    progress = Progress(image=image,id=p_id,
                        status=status)
                    detail = pr.get("progressDetail")
                    if detail:
                        progress.detail=json.dumps(detail)
                        progress.pr = pr.get("progress")
                    progress.save()
            image.status=Image.EXISTED
            image.save()
            print image.status
            return Response("Pulling complete")
        return Response("OK")

    @detail_route()
    def run(self,request,pk=None):
        container = get_object_or_404(self.queryset, pk=pk,user=request.user)
        cli = DockerClient().getClient()
        data={}
        print DockerClient().getHostConfig(
                    volumes=container.volumes,
                    links=container.links,
                    ports=container.ports,
                    restart=container.restart
                )
        if container.to_run():
            host_config =  DockerClient().getHostConfig(
                    volumes=container.volumes,
                    links=container.links,
                    ports=container.ports,
                    restart=container.restart
                )
            # print host_config
            command = container.command
            params={"name":container.name,"image":str(container.image),
            "host_config":host_config,"detach":True}
            if len(container.command)>0:
                params["command"]=container.command.split(",")
            if len(container.envs)>0:
                params["envs"]=container.envs.split(",")
            if len(container.ports)>0:
                ports=container.ports
                ports = ports.replace(":","")
                params['ports']=ports.split(",")
            data = cli.create_container(**params)
            if data.get("Id"):
                container.status=Container.EXISTED
                container.save()
                cli.start(container.name)
                return Response(True)
        elif container.is_existed():
            cli.start(container.name)
            return Response(True)

        # print data
        return Response(False)

    @detail_route()
    def stop(self,request,pk=None):
        container = get_object_or_404(self.queryset, pk=pk,user=request.user)
        cli = DockerClient().getClient()
        data = ContainerSerializer(container).data
        if container.status==Container.EXISTED:
            data=cli.stop(container.name)
        # print data
        return Response(data)

class RepoViewSet(viewsets.ViewSet):
    def list(self,request):
        base_url = "http://"+request.get_host()+request.path
        cli  = DockerHub()
        query = request.query_params.get("query")
        if query:
            data=cli.searchRepo(request.query_params)
        else:

            namespace = request.query_params.get("namespace")
            data = cli.getRepoList(namespace,request.query_params)

        r_previous = data.get('previous')
        r_next = data.get('next')
        if r_previous:
            pages=r_previous.split("?")
            data['previous'] = base_url+"?"+pages[1]
        if r_next:
            pages = r_next.split("?")
            data['next'] = base_url+"?"+pages[1]

        return Response(OrderedDict([
            ("count",data.get('count')),
            ("next",data.get('next')),
            ("previous",data.get('previous')),
            ("results",data.get('results'))]))

    def retrieve(self,request,pk=None):
        cli  = DockerHub()
        namespace = request.query_params.get("namespace")
        data=cli.getRepoDetail(pk,namespace)
        mk = data.get("full_description")
        if mk:
            data['full_description'] = markdown.markdown(mk,extensions=['markdown.extensions.tables','markdown.extensions.fenced_code'])
        else:
            return Response(data,status=404)
        return Response(data)

    @detail_route()
    def tags(self,request,pk=None):
        base_url = "http://"+request.get_host()+request.path
        cli = DockerHub()
        namespace = request.query_params.get("namespace")
        tag_name = request.query_params.get("name")
        # params={}
        # params['page']=request.query_params.get("page",1)
        # params['page_size'] = request.query_params.get('page_size')
        data=cli.getRepoTags(pk,namespace,tag_name,request.query_params)
        r_previous = data.get('previous')
        r_next = data.get('next')
        if r_previous:
            pages=r_previous.split("?")
            data['previous'] = base_url+"?"+pages[1]
        if r_next:
            pages = r_next.split("?")
            data['next'] = base_url+"?"+pages[1]
        return Response(OrderedDict([
            ("count",data.get('count')),
            ("next",data.get('next')),
            ("previous",data.get('previous')),
            ("results",data.get('results'))]))


class ImageViewSet(viewsets.ModelViewSet):

    queryset = Image.objects.all().order_by('-created')
    serializer_class = ImageSerializer
    pagination_class = StandardResultsSetPagination

    # def list(self, request):
        
    #     cli = DockerClient().getClient()
    #     try:
    #         images = cli.images()
    #     except errors.NotFound:
    #         pass
    #     else:
    #         return Response(images)

    # def retrieve(self, request, pk=None):
    #     cli = DockerClient().getClient()
    #     try:
    #         image = cli.inspect_image(pk)
    #     except errors.NotFound:
    #         return Response({"detail":"Not found."},status=404)
    #     else:
    #         return Response(image)

class FileViewSet(viewsets.ViewSet):
    def list(self,request):
        # path = request.query_params.get("path")
        # if path:
        #     path = request.user.username+"/"+path
        # else:
        #     path = request.user.username
        file_list = files.fileList(request.user.username)
        if file_list:
            return Response(file_list)
        return Response(status=404);

    # 上传文件
    def create(self, request,format=None):
        file_obj = request.data['file']
        status = files.fileUpload(str(file_obj),file_obj,request.user.username)
        
        # ...
        # do some stuff with uploaded file
        # ...
        return Response(status=status)