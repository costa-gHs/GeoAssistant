# novo arquivo: api/vector_store.py
from openai import OpenAI


class VectorStoreManager:
    def __init__(self, client: OpenAI):
        self.client = client

    async def create_store(self, name: str, files: list, expiration_days: int = 30):
        try:
            return await self.client.beta.vector_stores.create_and_poll(
                name=name,
                file_ids=files,
                expires_after={
                    "anchor": "last_active_at",
                    "days": expiration_days
                }
            )
        except Exception as e:
            print(f"Erro ao criar vector store: {e}")
            return None

    async def check_store_status(self, store_id: str):
        try:
            store = await self.client.beta.vector_stores.retrieve(store_id)
            return store.status == "completed"
        except Exception as e:
            print(f"Erro ao verificar status do store: {e}")
            return False