from .models import XTBConnection

class LiveStatusMiddleware:
    """
    Middleware dodający status LIVE do kontekstu szablonów.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            xtb_connection = XTBConnection.objects.filter(user=request.user).first()
            request.is_live = xtb_connection.is_live if xtb_connection else False
        else:
            request.is_live = False
        
        response = self.get_response(request)
        return response
