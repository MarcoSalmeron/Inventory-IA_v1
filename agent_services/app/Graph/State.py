from typing import TypedDict

class AgentState(TypedDict):
    request_id: str
    zip_path: str
    job_id: int
    description: str
    category_name: str
    primary_uom_val: str
    similarity_threshold: float