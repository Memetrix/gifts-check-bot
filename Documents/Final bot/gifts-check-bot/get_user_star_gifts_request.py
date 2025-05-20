from telethon.tl._tl import TLRequest, TLObject
from telethon.tl.types import InputUser
from io import BytesIO

class GetUserStarGiftsRequest(TLRequest):
    """
    Метод: payments.getUserStarGifts#5e72c7e1
    Возвращает список подарков, закреплённых на профиле пользователя.
    """

    CONSTRUCTOR_ID = 0x5e72c7e1
    SUBCLASS_OF_ID = 0x6b65b517
    QUALNAME = "payments.GetUserStarGifts"

    def __init__(self, *, user_id, offset="", limit=100):
        self.user_id = user_id
        self.offset = offset
        self.limit = limit

    def to_dict(self):
        return {
            '_': self.QUALNAME,
            'user_id': self.user_id.to_dict() if isinstance(self.user_id, TLObject) else self.user_id,
            'offset': self.offset,
            'limit': self.limit
        }

    def _bytes(self):
        b = BytesIO()
        b.write(self.CONSTRUCTOR_ID.to_bytes(4, 'little', signed=False))
        b.write(self.user_id._bytes())
        b.write(TLObject.serialize_bytes(self.offset))
        b.write(self.limit.to_bytes(4, 'little', signed=True))
        return b.getvalue()

    def write(self):
        return self._bytes()

    @classmethod
    def read(cls, b: BytesIO, *args):
        # Это может быть не нужен, но чтобы не падало при парсинге
        return cls(user_id=None, offset="", limit=0)