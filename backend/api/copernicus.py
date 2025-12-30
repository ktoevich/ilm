import requests

class CopernicusClient:
    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password
        self.token = None

    def authenticate(self):
        # Todo: Implement Keycloak auth
        pass

    def search_images(self, bbox, date_range):
        # Todo: Implement OData search
        return []

    def download_image(self, product_id):
        # Todo: Implement download
        return None
