from django.urls import path

from accounts import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("sign-in/", views.SignInView.as_view(), name="sign_in"),
    path("sign-out/", views.SignOutView.as_view(), name="sign_out"),
    path("account/", views.account, name="account"),
    path("password/change/", views.ChangePasswordView.as_view(), name="password_change"),
    path("password/changed/", views.ChangePasswordDoneView.as_view(), name="password_change_done"),
]
