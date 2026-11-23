from cryptography.fernet import Fernet

class RedditAdapterToken:
    """
    Class that holds and handles HTTP tokens
    
    All concrete implementations must inherit from this class and implement
    all abstract methods to provide a consistent interface for Reddit operations.
    """
    def __init__(self, key_settings_key: str, key_settings_token: str):
        self._key = None
        self._decrypted = None
        self._encrypted = None
        self._key_settings_key = key_settings_key
        self._key_settings_token = key_settings_token

    def get_key_settings_key(self) -> str:
        return self._key_settings_key

    def get_key_settings_token(self) -> str:
        return self._key_settings_token

    def reset(self):
        self._key = None
        self._decrypted = None
        self._encrypted = None

    def load (self, key:str, encrypted: str):
        if key is None or encrypted is None:
            return
        self._key = key
        self._encrypted = encrypted
        f = Fernet(key.encode())
        self._decrypted = f.decrypt(encrypted.encode()).decode()

    def set(self, decrypted: str) -> None:
        """
        Stores a plain-text token and its encrypted form, generating an encryption key if there is none yet.

        :param decrypted: The plain-text token.
        :type decrypted: str
        :return: None
        """
        if self._key is None:
            self._key = Fernet.generate_key().decode()
        self._decrypted = decrypted
        f = Fernet(self._key.encode())
        self._encrypted = f.encrypt(decrypted.encode()).decode()

    def get_key(self) -> str:
        return self._key

    def get_decrypted(self) -> str:
        return self._decrypted

    def get_encrypted(self) -> str:
        return self._encrypted

    def get_key_bytes(self) -> str:
        return self._key.encode()

    def get_decrypted_bytes(self) -> str:
        return self._decrypted.encode()

    def get_encrypted_bytes(self) -> str:
        return self._encrypted.encode()
