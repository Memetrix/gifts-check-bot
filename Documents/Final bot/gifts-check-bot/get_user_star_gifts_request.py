from telethon.tl.tlobject import TLObject
from telethon.tl.tlobject import TLRequest
from telethon.tl.types import InputUser
from io import BytesIO

class GetUserStarGiftsRequest(TLRequest):
    CONSTRUCTOR_ID = 0x5e72c7e1
    SUBCLASS_OF_ID = 0x6b65b517
    QUALNAME = "payments.GetUserStarGifts"

    def __init__(self, *, user_id, offset="", limit=100):
        self.user_id = user_id
        self.offset = offset
        self.limit = limit

    def write(self) -> bytes:
        return self._bytes()  # Telethon вызывает write → _bytes

    def _bytes(self) -> bytes:
        b = BytesIO()
        b.write(self.CONSTRUCTOR_ID.to_bytes(4, 'little', signed=False))
        b.write(self.user_id.write())
        b.write(TLObject.serialize_bytes(self.offset))
        b.write(self.limit.to_bytes(4, 'little', signed=True))
        return b.getvalue()

    def to_dict(self):
        return {
            '_': self.QUALNAME,
            'user_id': self.user_id.to_dict() if isinstance(self.user_id, TLObject) else self.user_id,
            'offset': self.offset,
            'limit': self.limit
        }
