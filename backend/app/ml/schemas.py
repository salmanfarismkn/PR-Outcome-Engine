from typing import Literal

from pydantic import BaseModel, Field


class PRRiskPredictionResponse(BaseModel):
    pull_request_id: int
    predicted_outcome: Literal["healthy", "problematic"]
    problematic_probability: float = Field(ge=0.0, le=1.0)
    model_version: str
    prediction_status: Literal["experimental"] = "experimental"