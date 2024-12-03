from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import bcrypt

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


# Funções de manipulação de dados
def adicionar_usuario():
    nome = input("Digite o nome do usuário: ")
    senha = input("Digite a senha: ")
    is_admin = input("O usuário é administrador? (s/n): ").lower() == 's'
    senha_criptografada = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    novo_usuario = Usuario(nome=nome, senha=senha_criptografada, data_ultimo_login=datetime.now(), is_admin=is_admin)
    db.session.add(novo_usuario)
    db.session.commit()
    print(f"Usuário '{nome}' adicionado com sucesso!")


def visualizar_usuarios():
    usuarios = Usuario.query.all()
    print("Usuários cadastrados:")
    for usuario in usuarios:
        print(
            f"ID: {usuario.id} | Nome: {usuario.nome} | Admin: {'Sim' if usuario.is_admin else 'Não'} | Último login: {usuario.data_ultimo_login}")


def excluir_usuario():
    visualizar_usuarios()
    usuario_id = int(input("Digite o ID do usuário que deseja excluir: "))
    usuario = Usuario.query.get(usuario_id)
    if usuario:
        db.session.delete(usuario)
        db.session.commit()
        print("Usuário excluído com sucesso!")
    else:
        print("Usuário não encontrado.")


def visualizar_conversas_usuario():
    usuario_id = int(input("Digite o ID do usuário para ver as conversas: "))
    conversas = Conversa.query.filter_by(id_usuario=usuario_id).all()
    if conversas:
        for conversa in conversas:
            print(
                f"Conversa ID: {conversa.id} | Data de Início: {conversa.data_inicio} | Thread ID: {conversa.thread_id}")
    else:
        print("Nenhuma conversa encontrada para este usuário.")


def excluir_conversa():
    visualizar_conversas_usuario()
    conversa_id = int(input("Digite o ID da conversa que deseja excluir: "))
    conversa = Conversa.query.get(conversa_id)
    if conversa:
        db.session.delete(conversa)
        db.session.commit()
        print("Conversa excluída com sucesso!")
    else:
        print("Conversa não encontrada.")


# Menu interativo
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


if __name__ == '__main__':
    with app.app_context():
        inicializar_db()
        menu()
