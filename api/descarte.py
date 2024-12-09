import bcrypt

# Gere um hash para a senha
senha_teste = "12341234"
hash_gerado = bcrypt.hashpw(senha_teste.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

print(f"Hash gerado: {hash_gerado}")
