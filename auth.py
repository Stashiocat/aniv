import json
import requests

class Auth():
    def __init__(self, auth_file):
        self.__auth_file = auth_file
        self.__auth_json = {}
        self.__load_auth()
        
    def get_user(self):
        return self.__auth_json['username']
    
    def get_client_id(self):
        return self.__auth_json['client_id']
        
    def get_client_secret(self):
        return self.__auth_json['client_secret']
    
    def get_irc_token(self):
        return self.__auth_json['irc_auth_token']
        
    def get_access_token(self):
        return self.__auth_json['access_token']
        
    def get_refresh_token(self):
        return self.__auth_json['refresh_token']
        
    def get_funtoon_token(self):
        return self.__auth_json['funtoon_token']

    def validate_access_token(self):
        headers = {
            'Authorization': f'OAuth {self.__auth.get_access_token()}'
        }
        
        r = requests.get('https://id.twitch.tv/oauth2/validate', headers=headers)
        j = json.loads(r.content)
        return 'client_id' in j
        
    def refresh_access_token(self):
        params = {
            'grant_type': 'refresh_token',
            'refresh_token': self.get_refresh_token(),
            'client_id': self.get_client_id(),
            'client_secret': self.get_client_secret()
        }
        
        url = 'https://id.twitch.tv/oauth2/token'

        r = requests.post(url, params=params)
        j = json.loads(r.content)
        new_access_token = j['access_token']
        new_refresh_token = j['refresh_token']
        self.__assign_new_access_token(new_access_token, new_refresh_token)
        return new_access_token
        
    ###########################################################################
    # Private helper methods
    ###########################################################################
    def __load_auth(self):
        try:
            with open(self.__auth_file, 'r') as f:
                self.__auth_json = json.load(f)
        except IOError:
            print(f"Unable to open auth file '{__auth_file}'")
            
    def __save_auth(self):
        with open(self.__auth_file, 'w') as f:
            json.dump(self.__auth_json, f, indent=4)
            
    def __assign_new_access_token(self, new_access_token, new_refresh_token):
        self.__auth_json['access_token'] = new_access_token
        self.__auth_json['refresh_token'] = new_refresh_token
        self.__save_auth()
        