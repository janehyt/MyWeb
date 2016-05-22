# -*- coding: UTF-8 -*- 
from django.shortcuts import get_object_or_404,redirect

# Create your views here.
from django.contrib.auth.models import User
from django.contrib import auth

from collections import OrderedDict
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.decorators import permission_classes,detail_route,list_route
from rest_framework.permissions import AllowAny,IsAuthenticated
from .serializers import UserSerializer
from .files import VolumeService
from django.http import StreamingHttpResponse


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
        user = auth.authenticate(username=data.get('username'),password = data.get('password'))
        if user and user.is_active:
            auth.login(request,user)
            serializer = self.get_serializer(user)
            # to = Token.objects.get_or_create(user=user)
            # print to
            return Response(serializer.data)
        validation_error="请输入正确的用户名和密码."
        return Response(validation_error,status=400)

    @list_route(methods=['POST'],permission_classes=[AllowAny,])
    def sign_up(self, request):
        data = request.data

        serializer = UserSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return self.sign_in(request)
        errors = ""
        if "username" in serializer.errors:
            errors = "用户名已存在,"
        if "email" in serializer.errors:
            errors+="邮箱已被注册,"
        return Response(errors[0:len(errors)-1],status=400)

    @list_route(methods=['POST'])
    def reset(self, request):
        data = request.data
        user = request.user
        oldpass = data['oldpass']
        password = data['password']
        if auth.authenticate(username=user.username,password = oldpass):
            user.set_password(password)
            user.save()
            # user = auth.authenticate(username=user.username,password = password)
            # auth.login(request,user)
            # print user.is_active
            return Response(True)
        

        return Response("原密码错误",status=400)
    @list_route(methods=['POST'])
    def log_out(self, request):
        m=auth.logout(request)
        return Response(m)

    @list_route()
    def load_user(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


class VolumeViewSet(viewsets.ViewSet):
    def list(self,request):
        path = request.query_params.get("path","")
        files = VolumeService(request.user,path)
        data = files.list()
        if data is None:
            return Response({"detail":"找不到指定路径"},status = 404)
        return Response(data);
    @list_route()
    def download(self,request):
        path = request.query_params.get("path","")
        files = VolumeService(request.user,path)
        data = files.download()
        if data is None:
            return Response({"detail":"找不到指定路径"},status = 404)
        response = StreamingHttpResponse(data.get("stream"))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="{0}"'.format(data.get("name"))
        return response

    # 上传文件
    def create(self, request,format=None):
        file_obj = request.data['file']
        path = request.query_params.get("path","")
        files = VolumeService(request.user,path)
        status = files.fileUpload(str(file_obj),file_obj)
        return Response(status=status)

    @list_route(methods=['POST'])
    def rename(self,request):
        path = request.data.get("path","")
        name = request.data.get("name","")
        if path and name:    
            files = VolumeService(request.user,path)
            return Response(files.rename(name))
        return Response({"detail":"请提供path和name"},status=406)

    @list_route(methods=['POST'])
    def remove(self,request):
        path = request.data.get("path","")
        # name = request.data.get("name","")
        if path: 
            files = VolumeService(request.user,path)
            return Response(files.remove())
        return Response({"detail":"请提供path"},status=406)

    @list_route(methods=['POST'])
    def mkdir(self,request):
        path = request.data.get("path","")
        name = request.data.get("name","")
        if name:    
            files = VolumeService(request.user,path)
            return Response(status=files.mkdir(name))
        return Response({"detail":"请提供path和name"},status=406)

    @list_route(methods=['POST'])
    def unzip(self,request):
        path = request.data.get("path","")       
        if path:    
            files = VolumeService(request.user,path)
            return Response(status=files.unzip())
        return Response({"detail":"请提供path"},status=406)

    # @list_route()
    # def remove(self,request):
    #     path = files.getUploadDir(str(request.user))
    #     filename = request.query_params.get("filename","")
    #     if len(filename):
    #         filename=os.path.join(path,filename)
    #         return Response(status=files.destroyFile(filename))
    #     return Response({"detail":"filename required"},status=406)