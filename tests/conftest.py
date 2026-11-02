import pytest

from email_task_agent.memory import MemoryStore


@pytest.fixture
def memory_store() -> MemoryStore:
    return MemoryStore()
