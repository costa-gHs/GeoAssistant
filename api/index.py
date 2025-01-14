from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from flask import abort
from openai import OpenAI
import time
import secrets
import bcrypt
from api.admin_routes import admin_routes_bp  # Novo nome do Blueprint
from api.database import db, Usuario, Conversa, Mensagem  # Importa db e modelos
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
    except Exception as e:
        print(f"Erro ao obter resposta: {e}")
        return None


def verificar_e_atualizar_uso(usuario_id, input_tokens, output_tokens):
    try:
        # Primeiro, verifica se já existe registro de uso para o mês atual
        data_atual = datetime.now()
        primeiro_dia_mes = data_atual.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Buscar ou criar registro de uso mensal
        response = supabase.table("user_usage_metrics") \
            .select("*") \
            .eq("usuario_id", usuario_id) \
            .gte("data_referencia", primeiro_dia_mes.isoformat()) \
            .execute()

        if not response.data:
            # Criar novo registro mensal
            supabase.table("user_usage_metrics").insert({
                "usuario_id": usuario_id,
                "data_referencia": primeiro_dia_mes.isoformat(),
                "total_tokens": input_tokens + output_tokens,
                "total_mensagens": 1
            }).execute()
        else:
            # Atualizar registro existente
            registro = response.data[0]
            supabase.table("user_usage_metrics") \
                .update({
                "total_tokens": registro["total_tokens"] + input_tokens + output_tokens,
                "total_mensagens": registro["total_mensagens"] + 1,
                "updated_at": datetime.now().isoformat()
            }) \
                .eq("id", registro["id"]) \
                .execute()

        # Verificar limites
        limites = supabase.table("user_limits") \
            .select("*") \
            .eq("usuario_id", usuario_id) \
            .execute()

        if limites.data:
            limite = limites.data[0]
            uso_atual = response.data[0]["total_tokens"] if response.data else (input_tokens + output_tokens)
            percentual_uso = (uso_atual / limite["limite_tokens_mensal"]) * 100

            if percentual_uso >= limite["alerta_uso_porcentagem"]:
                # Aqui você pode implementar o sistema de alertas
                print(f"Alerta: Usuário {usuario_id} atingiu {percentual_uso:.1f}% do limite mensal")

            if percentual_uso >= 100:
                return False, "Limite mensal de tokens atingido"

        return True, None

    except Exception as e:
        print(f"Erro ao verificar uso: {e}")
        return True, None  # Em caso de erro, permite o uso para não bloquear o usuário


def salvar_mensagem_com_metricas(usuario_id, id_conversa, texto_usuario, texto_gpt, input_tokens, output_tokens, modelo):
    try:
        # Primeiro verifica e atualiza o uso
        pode_continuar, mensagem = verificar_e_atualizar_uso(usuario_id, input_tokens, output_tokens)
        if not pode_continuar:
            raise Exception(mensagem)

        # Resto do código existente...
        conversa_query = supabase.table("conversas") \
            .select("id_modelo, assistant_id") \
            .eq("id", id_conversa) \
            .single() \
            .execute()

        mensagem_response = supabase.table("mensagens").insert({
            "id_conversa": id_conversa,
            "texto_usuario": texto_usuario,
            "texto_gpt": texto_gpt,
            "data_hora_envio": datetime.now().isoformat()
        }).execute()

        mensagem_id = mensagem_response.data[0]['id']

        metrics_data = {
            "usuario_id": usuario_id,
            "conversa_id": id_conversa,
            "mensagem_id": mensagem_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "modelo": modelo,
            "timestamp": datetime.now().isoformat()
        }

        if conversa_query.data and conversa_query.data.get('id_modelo'):
            metrics_data["id_modelo"] = conversa_query.data['id_modelo']

        supabase.table("token_metrics").insert(metrics_data).execute()

        return mensagem_id
    except Exception as e:
        print(f"Erro ao salvar mensagem e métricas: {e}")
        return None


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
            print(f"Chave API encontrada para o usuário {nome}: {chave['chave']}")

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

    pode_continuar, mensagem = verificar_limites_usuario(usuario_id)
    if not pode_continuar:
        return jsonify({'error': mensagem}), 429  # Too Many Requests

    # Busca a chave API associada ao usuário
    api_key = get_api_key(usuario_id)
    if not api_key:
        print(f"Erro: Chave API não configurada para o usuário ID {usuario_id}.")
        return jsonify({'error': 'Chave API não configurada para este usuário.'}), 400

    print(f"Chave API utilizada para o usuário ID {usuario_id}: {api_key}")
    client = OpenAI(api_key=api_key)



    # Obtém dados do request
    data = request.get_json()
    assistant_id = data.get('assistant_id')
    user_message = data.get('message')
    conversa_id = data.get('conversa_id')  # Pode ser None

    if 'file' in request.files:
        file = request.files['file']
        if file:
            message_file = client.files.create(
                file=file.stream,
                purpose="assistants"
            )

            # Adicionar arquivo ao vetor store da thread
            message_data = {
                "role": "user",
                "content": user_message,
                "attachments": [
                    {"file_id": message_file.id, "tools": [{"type": "file_search"}]}
                ]
            }
        else:
            message_data = {
                "role": "user",
                "content": user_message
            }

    # Adiciona logs para depuração
    print(f"assistant_id recebido: {assistant_id}")
    print(f"user_message recebido: {user_message}")

    # Validação de entrada
    if not assistant_id or not user_message:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    try:
        # Criação ou recuperação de uma conversa
        if not conversa_id:
            # Cria uma nova conversa e thread
            thread_id = create_thread(client)
            if not thread_id:
                return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500

            # Cria uma nova conversa no Supabase
            nova_conversa_response = supabase.table("conversas").insert({
                "id_usuario": usuario_id,
                "data_inicio": datetime.now().isoformat(),
                "assistant_id": assistant_id,
                "thread_id": thread_id,  # Salva thread_id imediatamente
                "id_modelo": None
            }).execute()

            conversa_id = nova_conversa_response.data[0]["id"]
        else:
            # Recupera a conversa existente
            conversa_response = supabase.table("conversas").select("*").eq("id", conversa_id).execute()
            conversa = conversa_response.data[0] if conversa_response.data else None

            if not conversa:
                return jsonify({'error': 'Conversa não encontrada.'}), 404

            thread_id = conversa.get("thread_id")
            if not thread_id:
                # Só cria nova thread se realmente não existir
                thread_id = create_thread(client)
                if not thread_id:
                    return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500
                supabase.table("conversas").update({"thread_id": thread_id}).eq("id", conversa_id).execute()

        if nova_conversa:
            # Buscar o modelo correspondente ao assistant_id
            try:
                modelo_query = supabase.table("ai_models") \
                    .select("id") \
                    .eq("assistant_id", assistant_id) \
                    .execute()

                if modelo_query.data:
                    id_modelo = modelo_query.data[0]['id']
                    # Atualizar a conversa com o id_modelo
                    supabase.table("conversas") \
                        .update({"id_modelo": id_modelo}) \
                        .eq("id", conversa_id) \
                        .execute()
            except Exception as e:
                print(f"Erro ao atualizar modelo da conversa: {e}")

        # Envia mensagem para a thread
        if not send_message(client, thread_id, user_message):
            return jsonify({'error': 'Erro ao enviar a mensagem.'}), 500

        # Executa a thread
        run_response = run_thread(client, thread_id, assistant_id)
        if not run_response:
            return jsonify({'error': 'Erro ao executar o tópico.'}), 500

        # Polling para obter a resposta
        # Polling para obter a resposta
        max_wait_time = 60
        poll_interval = 5
        total_waited = 0
        resposta = None

        while total_waited < max_wait_time:
            time.sleep(poll_interval)
            total_waited += poll_interval
            resposta_suja = get_response(client, thread_id)
            if resposta_suja:
                resposta = resposta_suja  # A resposta já está processada corretamente
                break

        if resposta:
            return jsonify({
                'status': 'pending',
                'run_id': run_response.id,
                'thread_id': thread_id,
                'conversa_id': conversa_id,
                'message': user_message
            })

            if not mensagem_response.data:
                return jsonify({'error': 'Erro ao salvar mensagem'}), 500

            mensagem_id = mensagem_response.data[0]['id']

            # Depois salvamos as métricas usando o ID obtido
            input_tokens = contar_tokens(user_message)
            output_tokens = contar_tokens(resposta)

            # Salvar métricas
            supabase.table("token_metrics").insert({
                "usuario_id": usuario_id,
                "conversa_id": conversa_id,
                "mensagem_id": mensagem_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "modelo": "4o-mini",
                "timestamp": datetime.now().isoformat()
            }).execute()

            return jsonify({
                'status': 'pending',
                'run_id': run_response.id,
                'thread_id': thread_id,
                'conversa_id': conversa_id,
                'message': user_message
            })
        else:
            return jsonify({'error': 'Não foi possível obter uma resposta do assistente.'}), 500


    except Exception as e:
        print(f"Erro ao processar o chat: {e}")
        return jsonify({'error': f'Erro ao processar o chat: {str(e)}'}), 500


# Adicionar nova rota para check_run
@app.route('/check_run')
def check_run():
    if 'usuario_id' not in session:
        return jsonify({'error': 'Usuário não autenticado'}), 403

    thread_id = request.args.get('thread_id')
    run_id = request.args.get('run_id')
    conversa_id = request.args.get('conversa_id')

    try:
        api_key = get_api_key(session['usuario_id'])
        if not api_key:
            return jsonify({'error': 'Chave API não configurada'}), 400

        client = OpenAI(api_key=api_key)

        # Verifica o status do run
        run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run_id
        )

        print(f"Status do run {run_id}: {run.status}")

        if run.status == 'completed':
            resposta = get_response(client, thread_id)
            if resposta:
                # Salva mensagem e métricas
                mensagem_id = salvar_mensagem_com_metricas(
                    usuario_id=session['usuario_id'],
                    id_conversa=conversa_id,
                    texto_usuario=request.args.get('message', ''),
                    texto_gpt=resposta,
                    input_tokens=contar_tokens(request.args.get('message', '')),
                    output_tokens=contar_tokens(resposta),
                    modelo="4o-mini"
                )
                return jsonify({
                    'status': 'completed',
                    'response': resposta,
                    'mensagem_id': mensagem_id
                })

        return jsonify({'status': run.status})

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
            nova_conversa["data_inicio"] = datetime.fromisoformat(nova_conversa["data_inicio"])
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