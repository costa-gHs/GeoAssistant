import os
from supabase import create_client, Client
import bcrypt

def hash_senha(senha):
    """Gera o hash da senha."""
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verificar_senha(senha, hash_armazenado):
    """Verifica se a senha corresponde ao hash."""
    return bcrypt.checkpw(senha.encode("utf-8"), hash_armazenado.encode("utf-8"))

# Configurações do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL") #"https://xtrtbojamxglxscpkrax.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY") #"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh0cnRib2phbXhnbHhzY3BrcmF4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzMyNTAxODQsImV4cCI6MjA0ODgyNjE4NH0.m0PKEYvBzbvZd-lt6nnZKBlngDVLS8gbgv3x13bK0W0"

# Inicializa o cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Função para testar o login
def testar_login(nome, senha):
    try:
        # Busca o usuário pelo nome
        response = supabase.table("usuarios").select("*").eq("nome", nome).execute()
        usuario = response.data[0] if response.data else None

        if not usuario:
            print("Usuário não encontrado.")
            return False

        # Verifica a senha
        if verificar_senha(senha, usuario["senha"]):
            print(f"Login bem-sucedido! Usuário: {usuario['nome']}")
            return True
        else:
            print("Senha incorreta.")
            return False
    except Exception as e:
        print(f"Erro ao realizar login: {e}")
        return False

def is_bcrypt_hash(value):
    return value.startswith("$2b$") or value.startswith("$2a$") or value.startswith("$2y$")

def get_api_key(user_id):
    try:
        print(f"Buscando chave API para o usuário ID {user_id}...")

        response = supabase.table("api_keys").select("*").eq("user_id", user_id).execute()
        data = response.data[0] if response.data else None

        if not data:
            print(f"Nenhuma chave API encontrada para o usuário ID {user_id}.")
            return None

        print(f"Chave API encontrada: {data['chave']}")
        return data["chave"]
    except Exception as e:
        print(f"Erro ao buscar a chave API para o usuário ID {user_id}: {e}")
        return None


# Atualizar senhas para hashes bcrypt
def atualizar_senhas_para_hash(table, column):
    try:
        # Obter todos os usuários
        response = supabase.table(table).select("*").execute()

        if not response.data:
            print("Nenhum usuário encontrado ou erro na consulta.")
            return

        datas = response.data
        for data in datas:
            if not is_bcrypt_hash(data[column]):  # Verifica se a senha não é um hash
                nova_senha_hash = bcrypt.hashpw(data[column].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

                # Atualiza a senha no banco de dados
                update_response = supabase.table(table).update({column: nova_senha_hash}).eq("id", data["id"]).execute()

        print("Atualização de senhas concluída!")
    except Exception as e:
        print(f"Erro ao atualizar as senhas: {e}")

# Executa a atualização
if __name__ == "__main__":
    atualizar_senhas_para_hash("api_keys", "chave")
