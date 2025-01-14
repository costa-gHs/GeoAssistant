from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from flask import abort
from openai import OpenAI
import time
import secrets
import bcrypt
from api.admin_routes import admin_routes_bp  # Novo nome do Blueprint
from api.database import db, Usuario, Conversa, Mensagem, APIKey, UserLimit, UserUsageMetric  # Importa db e modelos
from datetime import datetime as dt
from api.supabase_client import supabase, verificar_senha, get_api_key
from datetime import datetime
import tiktoken
from collections import defaultdict

app = Flask(__name__, static_folder='../static', template_folder='../templates')
app.secret_key = secrets.token_hex(16)

app.instance_path = '/tmp'

# Registra o Blueprint de administração
app.register_blueprint(admin_routes_bp, url_prefix='/admin')  # Rotas administrativas

# Funções auxiliares
def iniciar_conversa(usuario_id, assistant_id=None):
    try:
        conversa_data = {
            "id_usuario": usuario_id,
<<<<<<< HEAD
            "data_inicio": datetime.now().isoformat(),
            "assistant_id": assistant_id
        }

        # Buscar o modelo correspondente ao assistant_id se existir
        if assistant_id:
            modelo_query = supabase.table("ai_models") \
                .select("id") \
                .eq("assistant_id", assistant_id) \
                .single() \
                .execute()

            if modelo_query.data:
                conversa_data["id_modelo"] = modelo_query.data['id']

        response = supabase.table("conversas").insert(conversa_data).execute()
=======
            "data_inicio": datetime.now().isoformat()  # Sempre ISO8601
        }).execute()
>>>>>>> origin/main
        return response.data[0] if response.data else None

    except Exception as e:
        print(f"Erro ao iniciar conversa: {e}")
        return None


def salvar_mensagem(id_conversa, texto_usuario, texto_gpt):
    try:
        supabase.table("mensagens").insert({
            "id_conversa": id_conversa,
            "texto_usuario": texto_usuario,
            "texto_gpt": texto_gpt,
            "data_hora_envio": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f"Erro ao salvar mensagem: {e}")



def carregar_historico(usuario_id):
    try:
        conversas = supabase.table("conversas").select("*").eq("id_usuario", usuario_id).execute().data
        historico = []
        for conversa in conversas:
            # Converte string ISO8601 para datetime
            data_inicio = datetime.fromisoformat(conversa["data_inicio"])
            mensagens = supabase.table("mensagens").select("*").eq("id_conversa", conversa["id"]).execute().data
            historico.append({
                "conversa_id": conversa["id"],
                "data_inicio": data_inicio,  # Agora é um objeto datetime
                "mensagens": [
                    {
                        "usuario": mensagem["texto_usuario"],
                        "gpt": mensagem["texto_gpt"],
                        "data": datetime.fromisoformat(mensagem["data_hora_envio"])
                    }
                    for mensagem in mensagens
                ]
            })
        return historico
    except Exception as e:
        print(f"Erro ao carregar histórico: {e}")
        return []


# Função para listar os assistentes existentes com nomes e IDs
def get_assistants():
    try:
        api_key = session.get('api_key')
        if not api_key:
            return []
        client = OpenAI(api_key=api_key)
        response = client.beta.assistants.list(order="desc", limit=20)
        assistant_list = [{"id": assistant.id, "name": assistant.name or 'Sem Nome'} for assistant in response.data]
        return assistant_list
    except Exception as e:
        print(f"Erro ao buscar assistentes: {e}")
        return []

# Funções auxiliares que usam o cliente OpenAI
def create_thread(client):
    try:
        thread = client.beta.threads.create()
        print(f"Thread criada: {thread.id}")  # Debug
        return thread.id
    except Exception as e:
        print(f"Erro ao criar um tópico: {e}")
        return None

def send_message(client, thread_id, user_message):
    try:
        client.beta.threads.messages.create(
            thread_id=thread_id, role="user", content=user_message
        )
        print(f"Mensagem enviada para thread {thread_id}")  # Debug
        return True
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False

def run_thread(client, thread_id, assistant_id):
    try:
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
        )
        print(f"Thread {thread_id} executada com assistant_id {assistant_id}")  # Debug
        return run
    except Exception as e:
        print(f"Erro ao executar o tópico: {e}")
        return None

def contar_tokens(texto, modelo="gpt-4o-mini"):
    """
    Calcula o número de tokens para um texto usando o modelo especificado.
    """
    try:
        codificacao = tiktoken.encoding_for_model(modelo)
        return len(codificacao.encode(texto))
    except Exception as e:
        print(f"Erro ao contar tokens: {e}")
        return 0

<<<<<<< HEAD

def get_response(client, thread_id, modelo="gpt-3.5-turbo"):
    try:
        # Obter as mensagens da thread
        messages = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=1)

        # Pegar a última mensagem (que deve ser do assistente)
        if not messages.data:
            return None

        last_message = messages.data[0]

        # Verificar se é uma mensagem do assistente
        if last_message.role != 'assistant':
            return None

        # Extrair o texto da mensagem
        content_text = ""
        for content in last_message.content:
            if content.type == 'text':
                content_text += content.text.value

        if not content_text:
            return None

        print(f"Resposta do assistente encontrada: {content_text}")
        return content_text

=======
def get_response(client, thread_id, modelo="gpt-3.5-turbo"):
    try:
        # Obter as mensagens da thread
        response = client.beta.threads.messages.list(thread_id=thread_id, order="asc")

        # Verificar se a resposta é um dicionário e contém "data"
        if isinstance(response, dict) and "data" in response:
            messages = response["data"]
        elif hasattr(response, "data"):
            messages = response.data
        else:
            print("Erro: Resposta da API não contém mensagens válidas.")
            return None

        # Verificar mensagens
        if not messages:
            print("Nenhuma mensagem encontrada na thread.")
            return None

        # Encontrar a última mensagem do assistente
        last_message = next(
            (msg for msg in reversed(messages) if getattr(msg, "role", "") == "assistant"),
            None
        )

        if not last_message:
            print("Nenhuma resposta do assistente encontrada ainda.")
            return None

        # Processar o conteúdo da mensagem
        content_text = "".join(
            [block.text.value for block in getattr(last_message, "content", []) if block.type == "text"]
        )

        # Calcular tokens de entrada e saída
        input_tokens = sum(
            contar_tokens(
                "".join(
                    [block.text.value for block in getattr(msg, "content", []) if block.type == "text"]
                ),
                modelo,
            )
            for msg in messages
            if getattr(msg, "role", "") == "user"
        )
        output_tokens = contar_tokens(content_text, modelo)

        # Exibir os tokens calculados
        print(f"Tokens de entrada (input): {input_tokens}")
        print(f"Tokens de saída (output): {output_tokens}")
        print(f"Resposta do assistente: {content_text}")

        return content_text  # Retornar o texto da resposta
>>>>>>> origin/main
    except Exception as e:
        print(f"Erro ao obter resposta: {e}")
        return None


<<<<<<< HEAD
def verificar_e_atualizar_uso(usuario_id, input_tokens, output_tokens):
    try:
        # Buscar limites do usuário
        response = supabase.table("user_limits").select("*").eq("usuario_id", usuario_id).eq("ativo",
                                                                                             True).single().execute()
        if not response.data:
            return True, None  # Sem limites definidos

        user_limit = response.data

        # Buscar uso atual do mês
        primeiro_dia_mes = datetime.now().replace(day=1).date()
        uso_response = supabase.table("user_usage_metrics") \
            .select("*") \
            .eq("usuario_id", usuario_id) \
            .gte("data_referencia", primeiro_dia_mes.isoformat()) \
            .single() \
            .execute()

        if not uso_response.data:
            # Criar novo registro de uso
            novo_uso = {
                "usuario_id": usuario_id,
                "data_referencia": primeiro_dia_mes.isoformat(),
                "total_tokens": input_tokens + output_tokens,
                "total_mensagens": 1,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            supabase.table("user_usage_metrics").insert(novo_uso).execute()
            novo_total = input_tokens + output_tokens
        else:
            uso_mensal = uso_response.data
            novo_total = uso_mensal["total_tokens"] + input_tokens + output_tokens

            if novo_total > user_limit["limite_tokens_mensal"]:
                return False, "Limite mensal de tokens atingido"

            # Atualizar métricas
            supabase.table("user_usage_metrics") \
                .update({
                "total_tokens": novo_total,
                "total_mensagens": uso_mensal["total_mensagens"] + 1,
                "updated_at": datetime.now().isoformat()
            }) \
                .eq("id", uso_mensal["id"]) \
                .execute()

        # Verificar alertas
        if user_limit["limite_tokens_mensal"]:
            percentual_uso = (novo_total / user_limit["limite_tokens_mensal"]) * 100
            if percentual_uso >= user_limit["alerta_uso_porcentagem"]:
                # TODO: Implementar sistema de notificação
                print(f"Alerta: Usuário {usuario_id} atingiu {percentual_uso:.1f}% do limite mensal")

        return True, None

    except Exception as e:
        print(f"Erro ao verificar uso: {e}")
        return False, f"Erro ao verificar limites: {str(e)}"


def salvar_mensagem_com_metricas(usuario_id, id_conversa, texto_usuario, texto_gpt, input_tokens, output_tokens,
                                 modelo):
    try:
        # Primeiro verifica e atualiza o uso
        pode_continuar, mensagem = verificar_e_atualizar_uso(usuario_id, input_tokens, output_tokens)
        if not pode_continuar:
            raise Exception(mensagem)

        # Salva a mensagem
        mensagem_data = {
=======
def salvar_mensagem_com_metricas(usuario_id, id_conversa, texto_usuario, texto_gpt, input_tokens, output_tokens,
                                 modelo):
    try:
        # Salva a mensagem
        mensagem_response = supabase.table("mensagens").insert({
>>>>>>> origin/main
            "id_conversa": id_conversa,
            "texto_usuario": texto_usuario,
            "texto_gpt": texto_gpt,
            "data_hora_envio": datetime.now().isoformat()
<<<<<<< HEAD
        }

        mensagem_response = supabase.table("mensagens").insert(mensagem_data).execute()
        if not mensagem_response.data:
            raise Exception("Erro ao salvar mensagem")

        mensagem_id = mensagem_response.data[0]['id']

        # Busca informações da conversa
        conversa_response = supabase.table("conversas").select("id_modelo").eq("id", id_conversa).single().execute()

        # Salva as métricas de token
        metrics_data = {
=======
        }).execute()

        mensagem_id = mensagem_response.data[0]['id']

        # Salva as métricas
        supabase.table("token_metrics").insert({
>>>>>>> origin/main
            "usuario_id": usuario_id,
            "conversa_id": id_conversa,
            "mensagem_id": mensagem_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "modelo": modelo,
            "timestamp": datetime.now().isoformat()
<<<<<<< HEAD
        }

        if conversa_response.data and conversa_response.data.get('id_modelo'):
            metrics_data["id_modelo"] = conversa_response.data['id_modelo']

        supabase.table("token_metrics").insert(metrics_data).execute()

        return mensagem_id

=======
        }).execute()

        return mensagem_id
>>>>>>> origin/main
    except Exception as e:
        print(f"Erro ao salvar mensagem e métricas: {e}")
        return None

<<<<<<< HEAD

def verificar_limites_usuario(usuario_id):
    try:
        # Buscar uso atual do usuário
        usage_query = supabase.from_('vw_user_usage') \
            .select('*') \
            .eq('usuario_id', usuario_id) \
            .single() \
            .execute()

        if usage_query.data:
            usage = usage_query.data
            if usage['limite_tokens'] > 0 and usage['percentual_uso'] >= 100:
                return False, "Limite de tokens atingido"

            if usage['percentual_uso'] >= 80:  # Alerta de uso
                print(f"Alerta: Usuário {usuario_id} atingiu {usage['percentual_uso']}% do limite")

        return True, None
    except Exception as e:
        print(f"Erro ao verificar limites: {e}")
        return True, None

=======
>>>>>>> origin/main
def get_assistant_reply(messages):
    # Percorre as mensagens em ordem reversa para obter a resposta mais recente
    for message in reversed(messages.data):
        if message.role == 'assistant':
            content_blocks = message.content
            for block in content_blocks:
                if block.type == 'text':
                    text = block.text.value
                    print(f"Resposta do assistente encontrada: {text}")  # Debug
                    return text  # Retorna o texto da mensagem mais recente do assistente
    return None

async def check_run_status(client, thread_id, run_id):
    try:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        return run.status
    except Exception as e:
        print(f"Erro ao verificar status: {e}")
        return None

# Rota principal
@app.route('/')
def index():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    usuario_id = session['usuario_id']
    usuario_nome = session.get('usuario_nome', 'Usuário')
    is_admin = session.get('is_admin', False)

    # Busca assistentes do OpenAI
    assistants = get_assistants()

    # Carrega o histórico de conversas
    historico = carregar_historico(usuario_id)

    # Pega o assistant_id da querystring, caso exista
    assistant_id = request.args.get('assistant_id')

    return render_template(
        'index.html',
        usuario_nome=usuario_nome,
        is_admin=is_admin,
        assistants=assistants,
        historico=historico,
        selected_assistant_id=assistant_id
    )


@app.route('/home')
def home():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    usuario_nome = session.get('usuario_nome')

    # Verifica se o usuário é CaioD2G e redireciona ao chat
    if usuario_nome == 'CaioD2G':
        return redirect(url_for('index', assistant_id='asst_9pmT1xXEYD9aCYvyDHWlFGJK'))

    try:
        # Buscar modelos de IA
        response = supabase.table("ai_models").select("*").execute()
        ai_models = response.data

        # Estatísticas para admins
        stats = {}
        if session.get('is_admin'):
            # Total de usuários
            users_count = supabase.table("usuarios").select("count").execute()
            stats['total_usuarios'] = users_count.data[0]['count'] if users_count.data else 0

            # Conversas de hoje - Aqui está a correção
            today = datetime.now().strftime('%Y-%m-%d')
            conversas_hoje = supabase.table("conversas")\
                .select("count")\
                .gte("data_inicio", today)\
                .execute()
            stats['conversas_hoje'] = conversas_hoje.data[0]['count'] if conversas_hoje.data else 0

            # Total de tokens
            tokens = supabase.table("token_metrics")\
                .select("input_tokens,output_tokens")\
                .execute()
            total_tokens = sum([
                (t.get('input_tokens', 0) + t.get('output_tokens', 0))
                for t in tokens.data
            ]) if tokens.data else 0
            stats['total_tokens'] = total_tokens

        return render_template(
            'home.html',
            ai_models=ai_models,
            usuario_nome=session.get('usuario_nome'),
            is_admin=session.get('is_admin', False),
            **stats
        )

    except Exception as e:
        return render_template(
            'home.html',
            ai_models=[],
            error=str(e)
        )
@app.route('/debug-tables')
def debug_tables():
    try:
        # Consulta direta ao Supabase para listar tabelas no schema público
        response = supabase.table("information_schema.tables").select("table_name").eq("table_schema", "public").execute()
        tables = response.data  # Lista de tabelas
        print(f"Tabelas encontradas no banco de dados: {tables}")
        return jsonify({"tables": tables})
    except Exception as e:
        print(f"Erro ao listar tabelas: {e}")
        return jsonify({"error": str(e)}), 500



# Rota de login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        nome = request.form.get("nome")
        senha = request.form.get("senha")

        try:
            # Log de início do processo
            print(f"Iniciando login para o usuário: {nome}")

            # Busca o usuário no banco
            response = supabase.table("usuarios").select("*").eq("nome", nome).execute()
            usuario = response.data[0] if response.data else None

            if not usuario:
                print("Usuário não encontrado no banco de dados.")
                return render_template("login.html", error="Usuário ou senha inválidos.")

            # Verifica a senha
            if not verificar_senha(senha, usuario["senha"]):
                print("Senha inválida para o usuário.")
                return render_template("login.html", error="Usuário ou senha inválidos.")

            # Log de usuário encontrado
            print(f"Usuário {nome} autenticado com sucesso. ID: {usuario['id']}")

            # Verifica se há uma chave associada ao usuário
            chave_response = supabase.table("api_keys").select("*").eq("user_id", usuario["id"]).execute()
            chave = chave_response.data[0] if chave_response.data else None

            if not chave:
                print(f"Chave API não configurada para o usuário ID {usuario['id']}.")
                return render_template("login.html", error="Chave API não configurada para este usuário.")

            # Log da chave encontrada
            print(f"Chave API encontrada para o usuário {nome}")

            # Sessão inicializada
            session["usuario_id"] = usuario["id"]
            session["usuario_nome"] = usuario["nome"]
            session["is_admin"] = usuario.get("is_admin", False)
            session["api_key"] = chave["chave"]  # Armazena a API Key na sessão

            return redirect(url_for("home"))
        except Exception as e:
            print(f"Erro durante o login: {e}")
            return render_template("login.html", error=f"Erro interno no sistema.")

    return render_template("login.html")



@app.route('/set_api_key', methods=['POST'])
def set_api_key():
    data = request.get_json()
    api_key = data.get('api_key')
    if api_key:
        session['api_key'] = api_key
        session.pop('thread_id', None)
        session.pop('assistant_id', None)
        print("API key definida. Sessão atualizada.")  # Debug
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Chave da API ausente'}), 400

# Função para enviar mensagem
@app.route('/chat', methods=['POST'])
def chat():
    if 'usuario_id' not in session:
        return jsonify({'error': 'Usuário não autenticado'}), 403

    usuario_id = session['usuario_id']
    print(f"Processando chat para o usuário ID {usuario_id}...")

    # Verificações iniciais
    pode_continuar, mensagem = verificar_limites_usuario(usuario_id)
    if not pode_continuar:
        return jsonify({'error': mensagem}), 429

    # Busca a chave API associada ao usuário
    api_key = get_api_key(usuario_id)
    if not api_key:
        print(f"Erro: Chave API não configurada para o usuário ID {usuario_id}.")
        return jsonify({'error': 'Chave API não configurada para este usuário.'}), 400

    print(f"Chave API utilizada para o usuário ID {usuario_id}:")
    client = OpenAI(api_key=api_key)

    # Obtém dados do request
    data = request.get_json()
    assistant_id = data.get('assistant_id')
    user_message = data.get('message')
    conversa_id = data.get('conversa_id')
<<<<<<< HEAD
    thread_id = data.get('thread_id')

    # Verificação de uso
    response = supabase.table("vw_user_usage").select("*").eq("usuario_id", usuario_id).single().execute()
    if response.data and response.data.get('percentual_uso', 0) >= 100:
        return jsonify({'error': 'Limite mensal de tokens atingido'}), 429

    # Verificação de arquivos
    if 'file' in request.files:
        file = request.files['file']
        if file:
            message_file = client.files.create(
                file=file.stream,
                purpose="assistants"
            )
            message_data = {
                "role": "user",
                "content": user_message,
                "attachments": [
                    {"file_id": message_file.id, "tools": [{"type": "file_search"}]}
                ]
            }
=======

    print(f"assistant_id recebido: {assistant_id}")
    print(f"user_message recebido: {user_message}")
>>>>>>> origin/main

    if not assistant_id or not user_message:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    try:
        # Criação ou recuperação de uma conversa
        if not conversa_id:
<<<<<<< HEAD
            # Cria uma nova thread
=======
            nova_conversa_response = supabase.table("conversas").insert({
                "id_usuario": usuario_id,
                "data_inicio": datetime.now().isoformat()
            }).execute()
            nova_conversa = nova_conversa_response.data[0] if nova_conversa_response.data else None
            if not nova_conversa:
                raise ValueError("Erro ao criar nova conversa no Supabase.")

            conversa_id = nova_conversa["id"]
>>>>>>> origin/main
            thread_id = create_thread(client)
            if not thread_id:
                return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500

<<<<<<< HEAD
            # Cria uma nova conversa no Supabase
            nova_conversa_response = supabase.table("conversas").insert({
                "id_usuario": usuario_id,
                "data_inicio": datetime.now().isoformat(),
                "assistant_id": assistant_id,
                "thread_id": thread_id,
                "id_modelo": None
            }).execute()

            if not nova_conversa_response.data:
                return jsonify({'error': 'Erro ao criar conversa'}), 500

            conversa_id = nova_conversa_response.data[0]["id"]

            # Buscar e atualizar o modelo
            try:
                modelo_query = supabase.table("ai_models") \
                    .select("id") \
                    .eq("assistant_id", assistant_id) \
                    .single() \
                    .execute()

                if modelo_query.data:
                    supabase.table("conversas") \
                        .update({"id_modelo": modelo_query.data['id']}) \
                        .eq("id", conversa_id) \
                        .execute()
            except Exception as e:
                print(f"Erro ao atualizar modelo da conversa: {e}")
        else:
            # Recupera a conversa existente
            conversa_response = supabase.table("conversas").select("*").eq("id", conversa_id).single().execute()

            if not conversa_response.data:
=======
            supabase.table("conversas").update({"thread_id": thread_id}).eq("id", conversa_id).execute()
        else:
            conversa_response = supabase.table("conversas").select("*").eq("id", conversa_id).execute()
            conversa = conversa_response.data[0] if conversa_response.data else None
            if not conversa:
>>>>>>> origin/main
                return jsonify({'error': 'Conversa não encontrada.'}), 404

            thread_id = conversa_response.data.get("thread_id")
            if not thread_id:
                thread_id = create_thread(client)
                if not thread_id:
                    return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500
                supabase.table("conversas").update({"thread_id": thread_id}).eq("id", conversa_id).execute()

<<<<<<< HEAD
        # Envia mensagem para a thread
=======
        print(f"Usando thread_id: {thread_id}")

        # Envia mensagem
>>>>>>> origin/main
        if not send_message(client, thread_id, user_message):
            return jsonify({'error': 'Erro ao enviar a mensagem.'}), 500

        # Executa a thread
        run = run_thread(client, thread_id, assistant_id)
        if not run:
            return jsonify({'error': 'Erro ao executar o tópico.'}), 500

<<<<<<< HEAD
        # Retorna imediatamente com status pending
        return jsonify({
            'status': 'pending',
            'thread_id': thread_id,
            'run_id': run_response.id,
            'conversa_id': conversa_id,
            'message': user_message
=======
        # Verifica o status atual
        current_run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id
        )

        if current_run.status == 'completed':
            # Se já completou, processa e retorna a resposta
            resposta = get_response(client, thread_id)
            if resposta:
                # Salva a mensagem
                supabase.table("mensagens").insert({
                    "id_conversa": conversa_id,
                    "texto_usuario": user_message,
                    "texto_gpt": resposta,
                    "data_hora_envio": datetime.now().isoformat()
                }).execute()

                # Salva métricas
                input_tokens = contar_tokens(user_message)
                output_tokens = contar_tokens(resposta)
                salvar_mensagem_com_metricas(
                    usuario_id=session['usuario_id'],
                    id_conversa=conversa_id,
                    texto_usuario=user_message,
                    texto_gpt=resposta,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    modelo="4o-mini"
                )

                return jsonify({
                    'status': 'completed',
                    'response': resposta,
                    'conversa_id': conversa_id
                })

        # Se não completou, retorna status pendente para polling
        return jsonify({
            'status': current_run.status,
            'run_id': run.id,
            'thread_id': thread_id,
            'conversa_id': conversa_id,
            'message': user_message  # Inclui a mensagem original para salvar depois
>>>>>>> origin/main
        })

    except Exception as e:
        print(f"Erro ao processar o chat: {e}")
        return jsonify({'error': f'Erro ao processar o chat: {str(e)}'}), 500


<<<<<<< HEAD
# Adicionar nova rota para check_run
=======
>>>>>>> origin/main
@app.route('/check_run')
def check_run():
    if 'usuario_id' not in session:
        return jsonify({'error': 'Usuário não autenticado'}), 403

    thread_id = request.args.get('thread_id')
    run_id = request.args.get('run_id')
    conversa_id = request.args.get('conversa_id')
<<<<<<< HEAD
    message = request.args.get('message')

    try:
=======

    try:
        # Recupera a chave API
>>>>>>> origin/main
        api_key = get_api_key(session['usuario_id'])
        if not api_key:
            return jsonify({'error': 'Chave API não configurada'}), 400

        client = OpenAI(api_key=api_key)

<<<<<<< HEAD
        # Verificar status do run
=======
        # Verifica o status do run
>>>>>>> origin/main
        run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run_id
        )

        print(f"Status do run {run_id}: {run.status}")

        if run.status == 'completed':
<<<<<<< HEAD
            # Buscar resposta
            resposta = get_response(client, thread_id)

            if resposta:
                # Salvar mensagem e métricas
                mensagem_id = salvar_mensagem_com_metricas(
                    usuario_id=session['usuario_id'],
                    id_conversa=conversa_id,
                    texto_usuario=message,
                    texto_gpt=resposta,
                    input_tokens=contar_tokens(message),
                    output_tokens=contar_tokens(resposta),
                    modelo="4o-mini"
                )

                if mensagem_id:
                    return jsonify({
                        'status': 'completed',
                        'response': resposta,
                        'mensagem_id': mensagem_id
                    })

            return jsonify({'status': 'error', 'error': 'Não foi possível obter resposta'})

        elif run.status == 'failed':
            return jsonify({'status': 'failed', 'error': 'Run falhou'})
        else:
            # Status ainda pendente
            return jsonify({'status': run.status})

=======
            # Obtém a resposta
            resposta = get_response(client, thread_id)
            if resposta:
                # Salva a mensagem no Supabase
                supabase.table("mensagens").insert({
                    "id_conversa": conversa_id,
                    "texto_usuario": request.args.get('message', ''),
                    "texto_gpt": resposta,
                    "data_hora_envio": datetime.now().isoformat()
                }).execute()

                # Salva métricas
                input_tokens = contar_tokens(request.args.get('message', ''))
                output_tokens = contar_tokens(resposta)
                salvar_mensagem_com_metricas(
                    usuario_id=session['usuario_id'],
                    id_conversa=conversa_id,
                    texto_usuario=request.args.get('message', ''),
                    texto_gpt=resposta,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    modelo="4o-mini"
                )

                return jsonify({
                    'status': 'completed',
                    'response': resposta
                })

        return jsonify({'status': run.status})
>>>>>>> origin/main
    except Exception as e:
        print(f"Erro ao verificar status: {e}")
        return jsonify({'status': 'failed', 'error': str(e)})

@app.route('/conversa/<int:conversa_id>')
def get_conversa(conversa_id):
    usuario_id = session.get('usuario_id')
    try:
        # Busca conversa no Supabase
        conversa_response = supabase.table("conversas").select("*").eq("id", conversa_id).execute()
        conversa = conversa_response.data[0] if conversa_response.data else None

        if not conversa or conversa["id_usuario"] != usuario_id:
            return jsonify({'error': 'Conversa não encontrada ou não pertence ao usuário atual'}), 404

        # Busca mensagens associadas
        mensagens_response = supabase.table("mensagens") \
            .select("*") \
            .eq("id_conversa", conversa_id) \
            .order("data_hora_envio", desc=False) \
            .execute()

        mensagens = mensagens_response.data if mensagens_response.data else []

        # Processar mensagens incluindo o ID da mensagem
        mensagens_json = [
            {
                'id': mensagem["id"],  # Incluir o ID da mensagem
                'usuario': mensagem["texto_usuario"],
                'gpt': mensagem["texto_gpt"],
                'data_hora_envio': datetime.fromisoformat(mensagem["data_hora_envio"]).strftime('%d/%m/%Y %H:%M')
            }
            for mensagem in mensagens
        ]

        return jsonify({
            'mensagens': mensagens_json,
            'thread_id': conversa.get("thread_id")
        })
    except Exception as e:
        return jsonify({'error': f'Erro ao carregar conversa: {str(e)}'}), 500


@app.route('/nova_conversa', methods=['POST'])
def nova_conversa():
    try:
        data = request.get_json()
        assistant_id = data.get('assistant_id')

        nova_conversa = iniciar_conversa(
            session['usuario_id'],
            assistant_id=assistant_id
        )

        if nova_conversa:
<<<<<<< HEAD
            nova_conversa["data_inicio"] = datetime.fromisoformat(nova_conversa["data_inicio"])
=======
            nova_conversa["data_inicio"] = datetime.fromisoformat(nova_conversa["data_inicio"])  # Conversão
>>>>>>> origin/main
            session['conversa_id'] = nova_conversa["id"]
            return jsonify({
                'success': True,
                'conversa_id': nova_conversa["id"],
                'data_inicio': nova_conversa["data_inicio"].strftime('%d/%m/%Y %H:%M')
            })
        else:
            return jsonify({'success': False, 'message': 'Erro ao criar conversa.'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'}), 500

@app.route('/feedback', methods=['POST'])
def save_feedback():
    if 'usuario_id' not in session:
        return jsonify({'error': 'Usuário não autenticado'}), 403

    try:
        data = request.get_json()
        mensagem_id = data['mensagem_id']

        # Buscar informações da conversa/modelo
        info_query = supabase.table("mensagens") \
            .select("""
                *,
                conversas!inner(
                    id_modelo,
                    assistant_id
                )
            """) \
            .eq("id", mensagem_id) \
            .single() \
            .execute()

        # Preparar os dados do feedback
        feedback_data = {
            "mensagem_id": mensagem_id,
            "usuario_id": session['usuario_id'],
            "tipo": data['tipo'],
            "comentario": data.get('comentario', ''),
            "data_feedback": datetime.now().isoformat(),
            "resolvido": False
        }

        # Adicionar id_modelo apenas se existir
        if info_query.data and info_query.data.get('conversas') and info_query.data['conversas'].get('id_modelo'):
            feedback_data["id_modelo"] = info_query.data['conversas']['id_modelo']

        # Salvar feedback
        feedback_response = supabase.table("feedback").insert(feedback_data).execute()

        if not feedback_response.data:
            raise Exception('Erro ao salvar feedback no banco de dados')

        return jsonify({
            'success': True,
            'feedback_id': feedback_response.data[0]['id']
        })

    except Exception as e:
        print(f"Erro ao salvar feedback: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
