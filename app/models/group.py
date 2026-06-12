from typing import Optional
from pydantic import BaseModel


class Group(BaseModel):
    id: Optional[str] = None
    name: str
    jid: str
    category: Optional[str] = ""
    active: bool = True
