from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import bcrypt
from supabase_client import supabase, hash_senha

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///usuarios.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# Modelo de Usuário
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    senha = db.Column(db.String(255), nullable=False)  # Senha criptografada
    data_ultimo_login = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)  # Novo campo para permissões de administrador

    # Relacionamento com Conversas
    conversas = db.relationship('Conversa', backref='usuario', lazy=True)


# Modelo de Conversas
class Conversa(db.Model):
    __tablename__ = 'conversas'
    id = db.Column(db.Integer, primary_key=True)
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    data_inicio = db.Column(db.DateTime, default=datetime.utcnow)
    thread_id = db.Column(db.String(255), nullable=True)

    # Relacionamento com Mensagens
    mensagens = db.relationship('Mensagem', backref='conversa', lazy=True, cascade="all, delete-orphan")


# Modelo de Mensagens
class Mensagem(db.Model):
    __tablename__ = 'mensagens'
    id = db.Column(db.Integer, primary_key=True)
    id_conversa = db.Column(db.Integer, db.ForeignKey('conversas.id'), nullable=False)
    texto_usuario = db.Column(db.Text, nullable=False)
    texto_gpt = db.Column(db.Text, nullable=True)
    data_hora_envio = db.Column(db.DateTime, default=datetime.utcnow)


# Função para criar o banco de dados
def inicializar_db():
    with app.app_context():
        db.create_all()
        print("Banco de dados criado com sucesso!")


def adicionar_usuario():
    nome = input("Digite o nome do usuário: ")
    senha = input("Digite a senha: ")
    is_admin = input("O usuário é administrador? (s/n): ").lower() == 's'
    senha_criptografada = bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    """Cria um novo usuário no Supabase."""
    senha_hash = hash_senha(senha)
    try:
        supabase.table("usuarios").insert({
            "nome": nome,
            "senha": senha_hash,
            "is_admin": is_admin,
            "data_ultimo_login": None
        }).execute()
        print(f"Usuário '{nome}' criado com sucesso!")
    except Exception as e:
        print(f"Erro ao criar usuário: {e}")

def visualizar_usuarios():
    try:
        response = supabase.table("usuarios").select("*").execute()
        usuarios = response.data
        print("Usuários cadastrados:")
        for usuario in usuarios:
            print(
                f"ID: {usuario['id']} | Nome: {usuario['nome']} | Admin: {'Sim' if usuario['is_admin'] else 'Não'} | Último login: {usuario['data_ultimo_login']}"
            )
    except Exception as e:
        print(f"Erro ao listar usuários: {e}")

def excluir_usuario():
    visualizar_usuarios()
    usuario_id = int(input("Digite o ID do usuário que deseja excluir: "))
    try:
        supabase.table("usuarios").delete().eq("id", usuario_id).execute()
        print("Usuário excluído com sucesso!")
    except Exception as e:
        print(f"Erro ao excluir usuário: {e}")

def visualizar_conversas_usuario():
    usuario_id = int(input("Digite o ID do usuário para ver as conversas: "))
    try:
        response = supabase.table("conversas").select("*").eq("id_usuario", usuario_id).execute()
        conversas = response.data
        if conversas:
            for conversa in conversas:
                print(
                    f"Conversa ID: {conversa['id']} | Data de Início: {conversa['data_inicio']} | Thread ID: {conversa['thread_id']}"
                )
        else:
            print("Nenhuma conversa encontrada para este usuário.")
    except Exception as e:
        print(f"Erro ao listar conversas: {e}")

def excluir_conversa():
    visualizar_conversas_usuario()
    conversa_id = int(input("Digite o ID da conversa que deseja excluir: "))
    try:
        supabase.table("conversas").delete().eq("id", conversa_id).execute()
        print("Conversa excluída com sucesso!")
    except Exception as e:
        print(f"Erro ao excluir conversa: {e}")

def menu():
    print("\n--- Menu de Gerenciamento de Banco de Dados ---")
    print("1. Adicionar novo usuário")
    print("2. Visualizar todos os usuários")
    print("3. Excluir usuário")
    print("4. Visualizar conversas de um usuário")
    print("5. Excluir conversa")
    print("0. Sair")

    while True:
        opcao = input("\nEscolha uma opção: ")
        if opcao == '1':
            adicionar_usuario()
        elif opcao == '2':
            visualizar_usuarios()
        elif opcao == '3':
            excluir_usuario()
        elif opcao == '4':
            visualizar_conversas_usuario()
        elif opcao == '5':
            excluir_conversa()
        elif opcao == '0':
            print("Saindo...")
            break
        else:
            print("Opção inválida. Tente novamente.")

with app.app_context():
    db.create_all()
    # Inserir usuário inicial (opcional)
    admin = Usuario(nome="Dev-henrique", senha="123412341234", is_admin=True)
    db.session.add(admin)
    db.session.commit()
