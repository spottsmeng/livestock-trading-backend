from pydantic import BaseModel


class TicketResponse(BaseModel):
    ticket: str
