from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import User, AnonymousUser
from .models import UserProfile  # zakładam, że jest w 'api' (zmień na swoją lokalizację)

class CustomAuthentication(BaseAuthentication):
    keyword = b"token"  # 'Token' w nagłówku

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth:
            return None

        if auth[0].lower() != self.keyword:
            return None

        if len(auth) == 1:
            raise AuthenticationFailed("Invalid token header. No credentials provided.")
        elif len(auth) > 2:
            raise AuthenticationFailed("Invalid token header. Token string should not contain spaces.")

        try:
            token_key = auth[1].decode()
        except UnicodeError:
            raise AuthenticationFailed("Invalid token header. Token must be ASCII.")

        return self.authenticate_credentials(token_key)

    def authenticate_credentials(self, key):
        try:
            user_profile = UserProfile.objects.get(auth_token=key)
        except UserProfile.DoesNotExist:
            raise AuthenticationFailed("Invalid token")

        # Tworzymy tymczasowego usera Django
        user_mock = User(
            id=user_profile.user_id,
            username=f"micro_{user_profile.user_id}",
            is_active=True,
            is_staff=True,
            is_superuser=True
        )
        user_mock.set_unusable_password()
        return (user_mock, None)

class MicroserviceUser(AnonymousUser):
    """
    Dziedziczymy po AnonymousUser, ale nadpisujemy property
    tak, by faktycznie był traktowany przez DRF jako zalogowany.
    """

    def __init__(self, user_id):
        super().__init__()
        self.pk = user_id
        self.id = user_id
        # Dodatkowo ustawiamy flags – w niektórych przypadkach DRF
        # może sprawdzać is_active, is_staff itp.
        self.is_active = True
        self.is_staff = True
        self.is_superuser = True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False
