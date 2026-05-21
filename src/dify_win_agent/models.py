from pydantic import BaseModel, Field


class CommandSpec(BaseModel):
    id: str = Field(min_length=1)
    shell: str = Field(min_length=1)


class ExecuteRequest(BaseModel):
    task_id: str = Field(min_length=1)
    target_host: str = Field(min_length=1)
    commands: list[CommandSpec] = Field(min_length=1)


class DashboardSettingsRequest(BaseModel):
    port: int = Field(ge=1, le=65535)
    log_dir: str = Field(min_length=1)
    report_dir: str = Field(min_length=1)
