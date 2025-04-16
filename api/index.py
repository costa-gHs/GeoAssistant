from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from openai import OpenAI
import secrets
from api.admin_routes import admin_routes_bp
from api.supabase_client import supabase, verificar_senha, get_api_key
from api.rag_routes import rag_routes_bp
from datetime import datetime
import logging
import re
from difflib import SequenceMatcher
import uuid
from datetime import timedelta
import os

app = Flask(__name__, static_folder='../static', template_folder='../templates')
app.secret_key = secrets.token_hex(16)

#logging.basicConfig(level=logging.INFO)

app.instance_path = '/tmp'

# Registra o Blueprint de administração
app.register_blueprint(admin_routes_bp, url_prefix='/admin')  # Rotas administrativas
app.register_blueprint(rag_routes_bp)

app.config['SESSION_TYPE'] = 'filesystem'  # You can also use 'redis' if available
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)  # Extend session lifetime
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 3. Configure specific Vercel-friendly settings
if os.environ.get('VERCEL_ENV'):
    # Vercel-specific adjustments
    print("Running in Vercel environment, applying special configurations")
    app.config['SESSION_TYPE'] = 'null'  # Vercel's serverless functions can't use filesystem
    app.config['SESSION_USE_SIGNER'] = False  # Reduce cookie size

    # Make sure we preserve session integrity as much as possible
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Increase memory limit if possible
    if 'MEMORY_LIMIT' in os.environ:
        print(f"Memory limit set to: {os.environ['MEMORY_LIMIT']}")


# 4. Detect and log session issues
@app.before_request
def log_session_info():
    if 'usuario_id' in session:
        print(f"Active session for user ID: {session['usuario_id']}")
    else:
        print(f"No authenticated user in session. Session keys: {list(session.keys())}")


# 5. Add session debug endpoint
@app.route('/debug/session')
def debug_session():
    return jsonify({
        'session_active': bool(session),
        'session_keys': list(session.keys()),
        'usuario_id': session.get('usuario_id', None),
        'usuario_nome': session.get('usuario_nome', None),
        'session_cookie_config': {
            'secure': app.config.get('SESSION_COOKIE_SECURE'),
            'httponly': app.config.get('SESSION_COOKIE_HTTPONLY'),
            'samesite': app.config.get('SESSION_COOKIE_SAMESITE'),
            'session_type': app.config.get('SESSION_TYPE')
        }
    })

def format_large_number(value):
    """Formata números grandes com separadores de milhar"""
    try:
        return "{:,.0f}".format(float(value)).replace(",", ".")
    except (ValueError, TypeError):
        return "0"

# Registrar o filtro no app Flask
app.jinja_env.filters['format_number'] = format_large_number

def get_response_with_usage(client, thread_id):
    try:
        # Obter as mensagens da thread
        response = client.beta.threads.messages.list(
            thread_id=thread_id,
            order="desc",
            limit=1
        )

        if not response.data:
            return None, None

        message = response.data[0]

        # Extrair o conteúdo da mensagem
        content = "".join([
            block.text.value
            for block in message.content
            if block.type == "text"
        ])

        # Obter usage da run
        run = client.beta.threads.runs.list(
            thread_id=thread_id,
            limit=1
        )

        if run.data:
            usage = run.data[0].usage
            token_metrics = {
                'prompt_tokens': usage.prompt_tokens,
                'completion_tokens': usage.completion_tokens,
                'total_tokens': usage.total_tokens
            }
        else:
            token_metrics = None

        return content, token_metrics

    except Exception as e:
        print(f"Erro ao obter resposta e métricas: {e}")
        return None, None


def save_message_metrics(supabase_client, usuario_id, conversa_id, mensagem_id, token_metrics, modelo="gpt-4o"):
    try:
        if not token_metrics:
            return

        metrics_data = {
            "usuario_id": usuario_id,
            "conversa_id": conversa_id,
            "mensagem_id": mensagem_id,
            "input_tokens": token_metrics['prompt_tokens'],
            "output_tokens": token_metrics['completion_tokens'],
            "total_tokens": token_metrics['total_tokens'],
            "timestamp": datetime.now().isoformat(),
            "modelo": modelo  # Adicionando o modelo
        }

        return supabase_client.table("token_metrics").insert(metrics_data).execute()

    except Exception as e:
        print(f"Erro ao salvar métricas: {e}")
        return None


def verify_user_limits(supabase_client, usuario_id, token_metrics):
    try:
        if not token_metrics:
            return True, None

        # Buscar uso atual do mês
        usage_response = supabase_client.from_('vw_user_usage') \
            .select('*') \
            .eq('usuario_id', usuario_id) \
            .single() \
            .execute()

        # Buscar limites do usuário
        limits_response = supabase_client.table("user_limits") \
            .select("*") \
            .eq("usuario_id", usuario_id) \
            .single() \
            .execute()

        if not limits_response.data:
            return True, None  # Sem limites definidos

        current_usage = usage_response.data['total_tokens'] if usage_response.data else 0
        limit = limits_response.data['limite_tokens_mensal']

        # Projetar uso após esta mensagem
        projected_usage = current_usage + token_metrics['total_tokens']
        usage_percent = (projected_usage / limit) * 100

        if usage_percent >= 100:
            return False, "Limite mensal de tokens atingido"

        if usage_percent >= limits_response.data['alerta_uso_porcentagem']:
            print(f"ALERTA: Usuário {usuario_id} atingirá {usage_percent:.1f}% do limite mensal")

        return True, None

    except Exception as e:
        print(f"Erro ao verificar limites: {e}")
        return True, None

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


def carregar_historico(usuario_id, limite=10, include_messages=False):
    """
    Carrega o histórico de conversas de forma otimizada.

    Args:
        usuario_id: ID do usuário
        limite: Número máximo de conversas a retornar (padrão: 10)
        include_messages: Se True, inclui as mensagens das conversas

    Returns:
        Uma lista de conversas, ordenadas por data de início (mais recentes primeiro)
    """
    try:
        # Buscar apenas as conversas mais recentes, com limite
        conversas = supabase.table("conversas") \
            .select("*") \
            .eq("id_usuario", usuario_id) \
            .order("data_inicio", desc=True) \
            .limit(limite) \
            .execute()

        conversas_data = conversas.data if conversas.data else []

        if not include_messages:
            # Se não precisar das mensagens, retorna apenas os metadados das conversas
            return [
                {
                    "conversa_id": conversa["id"],
                    "data_inicio": datetime.fromisoformat(conversa["data_inicio"]),
                    "thread_id": conversa.get("thread_id"),
                    "assistant_id": conversa.get("assistant_id"),
                    "mensagens": []  # Lista vazia, já que não estamos buscando mensagens
                }
                for conversa in conversas_data
            ]

        # Se precisar das mensagens, otimiza fazendo uma única requisição com filtro IN
        if conversas_data:
            conversa_ids = [conversa["id"] for conversa in conversas_data]

            # Buscar todas as mensagens de todas as conversas em uma única requisição
            mensagens = supabase.table("mensagens") \
                .select("*") \
                .in_("id_conversa", conversa_ids) \
                .execute()

            mensagens_data = mensagens.data if mensagens.data else []

            # Organizar mensagens por conversa_id para facilitar o processamento
            mensagens_por_conversa = {}
            for mensagem in mensagens_data:
                conversa_id = mensagem["id_conversa"]
                if conversa_id not in mensagens_por_conversa:
                    mensagens_por_conversa[conversa_id] = []
                mensagens_por_conversa[conversa_id].append(mensagem)

            # Construir o resultado final
            historico = []
            for conversa in conversas_data:
                conversa_id = conversa["id"]
                mensagens_conversa = mensagens_por_conversa.get(conversa_id, [])

                historico.append({
                    "conversa_id": conversa_id,
                    "data_inicio": datetime.fromisoformat(conversa["data_inicio"]),
                    "thread_id": conversa.get("thread_id"),
                    "assistant_id": conversa.get("assistant_id"),
                    "mensagens": [
                        {
                            "usuario": mensagem["texto_usuario"],
                            "gpt": mensagem["texto_gpt"],
                            "data": datetime.fromisoformat(mensagem["data_hora_envio"])
                        }
                        for mensagem in mensagens_conversa
                    ]
                })

            return historico

        return []

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


def print_debug_info(message, data, level="INFO"):
    print(f"\n{'=' * 50}")
    print(f"[{level}] {message}")
    print(f"{'=' * 50}")
    print(f"Data: {data}")
    print(f"{'=' * 50}\n")


def get_conversation_context(client, thread_id, max_messages=10):
    print_debug_info("Iniciando get_conversation_context", f"Thread ID: {thread_id}")
    try:
        messages = client.beta.threads.messages.list(
            thread_id=thread_id,
            order="desc",
            limit=max_messages
        )

        conversation_history = []
        last_assistant_messages = []
        message_count = {}

        for msg in messages.data:
            content = [block.text.value for block in msg.content if block.type == "text"]
            content = content[0] if content else ""

            if msg.role == "assistant":
                # Normalizar a mensagem removendo espaços extras
                normalized_message = re.sub(r'\s+', ' ', content.lower().strip())
                last_assistant_messages.append(normalized_message)
                message_count[normalized_message] = message_count.get(normalized_message, 0) + 1

                print_debug_info("Mensagem do assistente", {
                    "original": content,
                    "normalized": normalized_message,
                    "count": message_count[normalized_message]
                })

            conversation_history.append({
                "role": msg.role,
                "content": content
            })

        # Verificar repetições exatas
        repetition_detected = any(count >= 2 for count in message_count.values())

        # Verificar similaridade entre as últimas mensagens
        similar_messages = False
        if len(last_assistant_messages) >= 2:
            for i in range(len(last_assistant_messages) - 1):
                current_message = last_assistant_messages[i]
                next_message = last_assistant_messages[i + 1]

                similarity = SequenceMatcher(None, current_message, next_message).ratio()

                print_debug_info("Análise de similaridade de mensagens", {
                    "message1": current_message[:100] + "...",
                    "message2": next_message[:100] + "...",
                    "similarity": similarity
                })

                if similarity > 0.8:  # 80% similar
                    similar_messages = True
                    print_debug_info("Similaridade alta detectada!", {
                        "similarity": similarity,
                        "messages": [current_message, next_message]
                    })
                    break

        result = {
            "has_repetition": repetition_detected or similar_messages,
            "context": conversation_history,
            "message_count": message_count,
            "similar_messages_found": similar_messages,
            "last_messages": last_assistant_messages[:3]
        }

        print_debug_info("Resultado da análise", {
            "repetition_detected": repetition_detected,
            "similar_messages_found": similar_messages,
            "message_counts": {k[:50] + "...": v for k, v in message_count.items()},
            "last_messages": [msg[:50] + "..." for msg in last_assistant_messages[:3]]
        })

        return result

    except Exception as e:
        print_debug_info("Erro em get_conversation_context", str(e), "ERROR")
        return {
            "has_repetition": False,
            "context": []
        }

def handle_repetitive_questions(client, thread_id, message):
    context = get_conversation_context(client, thread_id)

    if context["has_repetition"]:
        instruction = """
        ALERTA: DETECTADA REPETIÇÃO NO PADRÃO DE RESPOSTA!

        Análise do histórico mostra que estamos em um loop de respostas similares.

        INSTRUÇÕES OBRIGATÓRIAS:
        1. PARE de usar o mesmo padrão de resposta
        2. NÃO use a estrutura "Com a confirmação de..."
        3. MUDE COMPLETAMENTE a abordagem do diagnóstico
        4. Faça um resumo dos problemas identificados até agora
        5. Sugira ações práticas de manutenção específicas
        6. Se necessário, recomende inspeção especializada

        CONTEXTO ATUAL:
        {message}
        """

        print_debug_info("Instrução gerada para evitar repetição", instruction)
        return instruction

    return message

def send_message(client, thread_id, message):
    try:
        if isinstance(message, dict):
            client.beta.threads.messages.create(
                thread_id=thread_id,
                **message
            )
        else:
            # Processar mensagem para evitar repetições
            processed_message = handle_repetitive_questions(client, thread_id, message)
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=processed_message
            )
        return True
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False


def run_thread(client, thread_id, assistant_id):
    print_debug_info("Iniciando run_thread", {
        "thread_id": thread_id,
        "assistant_id": assistant_id
    })

    try:
        instructions = """
        INSTRUÇÕES DE DIAGNÓSTICO:
        1. Mantenha um histórico claro das perguntas já feitas
        2. Evite repetir perguntas ou fazer perguntas muito similares
        3. Se uma questão não for respondida após 2 tentativas, mude a abordagem
        4. Explore diferentes aspectos do problema em cada pergunta
        5. Priorize diagnósticos práticos e ações concretas
        6. Se detectar um padrão circular, sugira ações específicas de manutenção
        7. Mantenha o foco no problema principal relatado
        8. Caso necessário, solicite informações adicionais específicas
        9. Na nona pergunta, faça uma avaliação geral e sugira próximos passos
        10. Evite fazer mais de 10 perguntas no total
        """

        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
            additional_instructions=instructions
        )

        print_debug_info("Thread executada com sucesso", {
            "run_id": run.id,
            "status": run.status
        })

        return run
    except Exception as e:
        print_debug_info("Erro ao executar thread", str(e), "ERROR")
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

    # Carrega apenas os metadados das conversas recentes, sem mensagens
    historico = carregar_historico(usuario_id, limite=10, include_messages=False)

    # Pega o assistant_id da querystring, caso exista
    assistant_id = request.args.get('assistant_id')

    # Escolhe o template com base no ID do assistente
    if assistant_id == 'asst_NjQVLJS3Ax11WbThZyNsS0gl':
        # Este é o assistente específico de componentes
        return render_template(
            'troubleshooting_focado.html',
            usuario_nome=usuario_nome,
            is_admin=is_admin,
            assistants=assistants,
            historico=historico,
            selected_assistant_id=assistant_id
        )
    elif assistant_id == 'asst_LqpNV5KZlig3wHiaY7RaAofw':
        # Este é o assistente RAG
        return render_template(
            'rag_troubleshooting.html',
            usuario_nome=usuario_nome,
            is_admin=is_admin,
            assistants=assistants,
            historico=historico,
            selected_assistant_id=assistant_id
        )
    else:
        # Usa o template padrão para todos os outros assistentes
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
    usuario_id = session.get('usuario_id')

    try:
        # Buscar modelos de IA
        response = supabase.table("ai_models").select("*").execute()
        ai_models = response.data

        # Buscar custos de tokens do usuário
        token_costs = supabase.from_('vw_token_costs') \
            .select('*') \
            .eq('usuario_id', usuario_id) \
            .execute()

        # Organizar custos por modelo
        costs_by_model = {}
        total_cost = 0.0  # Inicializado como float
        if token_costs.data:
            for cost in token_costs.data:
                model_name = cost.get('modelo', 'Desconhecido')
                # Garantir que todos os valores numéricos são float ou 0
                costs_by_model[model_name] = {
                    'input_tokens': float(cost.get('total_input_tokens') or 0),
                    'output_tokens': float(cost.get('total_output_tokens') or 0),
                    'total_tokens': float(cost.get('total_tokens') or 0),
                    'cost': float(cost.get('estimated_cost') or 0),
                    'price_per_million': float(cost.get('text_tokens_price') or 0)
                }
                total_cost += float(cost.get('estimated_cost') or 0)

        # Estatísticas para admins
        stats = {
            'total_cost': total_cost  # Movido para dentro do stats
        }

        if session.get('is_admin'):
            # Total de usuários
            users_count = supabase.table("usuarios").select("count").execute()
            stats['total_usuarios'] = users_count.data[0]['count'] if users_count.data else 0

            # Conversas de hoje
            today = datetime.now().strftime('%Y-%m-%d')
            conversas_hoje = supabase.table("conversas") \
                .select("count") \
                .gte("data_inicio", today) \
                .execute()
            stats['conversas_hoje'] = conversas_hoje.data[0]['count'] if conversas_hoje.data else 0

            # Total de tokens
            stats['total_tokens'] = sum(
                model['total_tokens'] for model in costs_by_model.values()
            )

        return render_template(
            'home.html',
            ai_models=ai_models,
            usuario_nome=usuario_nome,
            is_admin=session.get('is_admin', False),
            token_costs=costs_by_model,
            **stats
        )
    except Exception as e:
        print(f"Erro na rota home: {e}")
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
def chat_with_rag():
    """
    Modified chat endpoint to include RAG context.
    """
    if 'usuario_id' not in session:
        return jsonify({'error': 'Usuário não autenticado'}), 403

    request_id = str(uuid.uuid4())[:8]
    usuario_id = session['usuario_id']

    # Verificar limites de uso
    pode_continuar, mensagem = verificar_limites_usuario(usuario_id)
    if not pode_continuar:
        return jsonify({'error': mensagem}), 429

    # Buscar a chave API
    api_key = get_api_key(usuario_id)
    if not api_key:
        return jsonify({'error': 'Chave API não configurada para este usuário.'}), 400

    client = OpenAI(api_key=api_key)
    data = request.get_json()

    assistant_id = data.get('assistant_id')
    user_message = data.get('message')
    conversa_id = data.get('conversa_id')
    technical_context = data.get('technical_context')
    is_retry = data.get('is_retry', False)

    if not assistant_id or not user_message:
        return jsonify({'error': 'Parâmetros inválidos'}), 400

    try:
        nova_conversa = False
        if not conversa_id:
            thread_id = create_thread(client)
            if not thread_id:
                return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500

            # Add technical context if provided
            if technical_context:
                client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=f"CONTEXTO TÉCNICO:\n{technical_context}"
                )

            # Add RAG context if this is the RAG assistant
            if assistant_id == "asst_LqpNV5KZlig3wHiaY7RaAofw":
                try:
                    from api.llama_cloud_integration import llama_rag

                    rag_context = llama_rag.retrieve_context(user_message)
                    if rag_context:
                        rag_content = "CONTEXTO DE CONHECIMENTO RAG:\n"
                        for item in rag_context:
                            rag_content += f"---\n{item['text']}\n"

                        client.beta.threads.messages.create(
                            thread_id=thread_id,
                            role="user",
                            content=rag_content
                        )
                except Exception as rag_err:
                    print(f"rag_err{rag_err}")


            nova_conversa_response = supabase.table("conversas").insert({
                "id_usuario": usuario_id,
                "data_inicio": datetime.now().isoformat(),
                "assistant_id": assistant_id,
                "thread_id": thread_id,
                "id_modelo": None
            }).execute()

            conversa_id = nova_conversa_response.data[0]["id"]
            nova_conversa = True
        else:
            conversa_response = supabase.table("conversas").select("*").eq("id", conversa_id).execute()
            conversa = conversa_response.data[0] if conversa_response.data else None

            if not conversa:
                return jsonify({'error': 'Conversa não encontrada.'}), 404

            thread_id = conversa.get("thread_id")
            if not thread_id:
                thread_id = create_thread(client)
                if not thread_id:
                    return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500
                supabase.table("conversas").update({"thread_id": thread_id}).eq("id", conversa_id).execute()

        # Process message with RAG context if needed
        final_message = user_message

        # Only add RAG if this is the RAG assistant
        if assistant_id == "asst_LqpNV5KZlig3wHiaY7RaAofw":
            try:
                from api.llama_cloud_integration import llama_rag

                rag_context = llama_rag.retrieve_context(user_message)

                if rag_context:
                    # Add RAG context as system instructions rather than a separate message
                    # This keeps the context for this specific message but doesn't clutter the thread
                    rag_content = "IMPORTANTE - USE ESTE CONHECIMENTO PARA RESPONDER:\n"
                    for item in rag_context:
                        rag_content += f"---\n{item['text']}\n"

                    # Add the knowledge to the user message
                    final_message = f"{rag_content}\n\nPERGUNTA DO USUÁRIO:\n{user_message}"

            except Exception as rag_err:
                print(f"rag_err{rag_err}")


        # Send the message
        success = send_message(client, thread_id, final_message)
        if not success:
            return jsonify({'error': 'Erro ao enviar a mensagem.'}), 500

        # Run the thread
        run_response = run_thread(client, thread_id, assistant_id)
        if not run_response:
            return jsonify({'error': 'Erro ao executar o tópico.'}), 500

        return jsonify({
            'status': 'pending',
            'run_id': run_response.id,
            'thread_id': thread_id,
            'conversa_id': conversa_id,
            'message': user_message,
            'is_retry': is_retry
        })

    except Exception as e:

        return jsonify({'error': f'Erro ao processar o chat: {str(e)}'}), 500
def chat():
    if 'usuario_id' not in session:
        return jsonify({'error': 'Usuário não autenticado'}), 403

    request_id = str(uuid.uuid4())[:8]  # ID único para rastrear essa requisição em logs


    usuario_id = session['usuario_id']

    # Verificar limites de uso
    pode_continuar, mensagem = verificar_limites_usuario(usuario_id)
    if not pode_continuar:

        return jsonify({'error': mensagem}), 429

    # Buscar a chave API
    api_key = get_api_key(usuario_id)
    if not api_key:

        return jsonify({'error': 'Chave API não configurada para este usuário.'}), 400

    client = OpenAI(api_key=api_key)
    data = request.get_json()

    assistant_id = data.get('assistant_id')
    user_message = data.get('message')
    conversa_id = data.get('conversa_id')
    technical_context = data.get('technical_context')
    is_retry = data.get('is_retry', False)  # Flag para identificar tentativas de recuperação

    if not assistant_id or not user_message:

        return jsonify({'error': 'Parâmetros inválidos'}), 400

    try:
        nova_conversa = False
        if not conversa_id:


            thread_id = create_thread(client)
            if not thread_id:

                return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500

            if technical_context:
                client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=f"CONTEXTO TÉCNICO:\n{technical_context}"
                )

            nova_conversa_response = supabase.table("conversas").insert({
                "id_usuario": usuario_id,
                "data_inicio": datetime.now().isoformat(),
                "assistant_id": assistant_id,
                "thread_id": thread_id,
                "id_modelo": None
            }).execute()

            conversa_id = nova_conversa_response.data[0]["id"]
            nova_conversa = True

        else:


            conversa_response = supabase.table("conversas").select("*").eq("id", conversa_id).execute()
            conversa = conversa_response.data[0] if conversa_response.data else None

            if not conversa:

                return jsonify({'error': 'Conversa não encontrada.'}), 404

            thread_id = conversa.get("thread_id")
            if not thread_id:
                thread_id = create_thread(client)
                if not thread_id:

                    return jsonify({'error': 'Erro ao criar uma nova thread.'}), 500
                supabase.table("conversas").update({"thread_id": thread_id}).eq("id", conversa_id).execute()


        # Processar mensagem com controle de repetição
        final_message = user_message

        # Se for uma tentativa de recuperação, adicione instruções especiais
        if is_retry:

            recovery_instructions = """
            INSTRUÇÃO ESPECIAL DE RECUPERAÇÃO:
            Houve um timeout na resposta anterior. 
            1. Continue de onde parou ou forneça uma resposta mais concisa
            2. Evite respostas longas ou complexas
            3. Foque nos pontos mais importantes para responder ao usuário
            4. Se estava no meio de um diagnóstico, forneça uma conclusão parcial

            Mensagem original do usuário:
            """
            final_message = f"{recovery_instructions}\n{user_message}"
        else:
            final_message = handle_repetitive_questions(client, thread_id, user_message)

        # Adicionar contexto técnico se necessário e não for uma nova conversa
        if technical_context and not nova_conversa and not is_retry:
            final_message = f"CONTEXTO TÉCNICO:\n{technical_context}\n\nPERGUNTA DO USUÁRIO:\n{final_message}"


        success = send_message(client, thread_id, final_message)
        if not success:

            return jsonify({'error': 'Erro ao enviar a mensagem.'}), 500

        # Adicionar timeout maior para runs em tentativas de recuperação
        run_response = run_thread(client, thread_id, assistant_id)
        if not run_response:

            return jsonify({'error': 'Erro ao executar o tópico.'}), 500


        return jsonify({
            'status': 'pending',
            'run_id': run_response.id,
            'thread_id': thread_id,
            'conversa_id': conversa_id,
            'message': user_message,
            'is_retry': is_retry
        })

    except Exception as e:

        return jsonify({'error': f'Erro ao processar o chat: {str(e)}'}), 500

# Adicionar nova rota para check_run
@app.route('/check_run')
def check_run():
    if 'usuario_id' not in session:
        return jsonify({'error': 'Usuário não autenticado'}), 403

    thread_id = request.args.get('thread_id')
    run_id = request.args.get('run_id')
    conversa_id = request.args.get('conversa_id')
    message = request.args.get('message', '')  # Recuperar a mensagem original

    try:
        api_key = get_api_key(session['usuario_id'])
        if not api_key:
            return jsonify({'error': 'Chave API não configurada'}), 400

        client = OpenAI(api_key=api_key)

        # Verifica o status do run com timeout ajustado
        run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run_id
        )

        if run.status == 'completed':
            # Obtém resposta e métricas de uso
            resposta, token_metrics = get_response_with_usage(client, thread_id)

            if resposta:
                # Verifica limites antes de salvar
                pode_continuar, mensagem = verify_user_limits(
                    supabase,
                    session['usuario_id'],
                    token_metrics
                )

                if not pode_continuar:
                    return jsonify({
                        'status': 'error',
                        'error': mensagem
                    }), 429

                # Salva a mensagem
                mensagem_response = supabase.table("mensagens").insert({
                    "id_conversa": conversa_id,
                    "texto_usuario": message or request.args.get('message', ''),
                    "texto_gpt": resposta,
                    "data_hora_envio": datetime.now().isoformat()
                }).execute()

                if mensagem_response.data:
                    mensagem_id = mensagem_response.data[0]['id']

                    # Usar sempre o modelo 4o-mini para métricas
                    modelo = "4o-mini"  # Definindo modelo fixo

                    # Salva as métricas
                    save_message_metrics(
                        supabase,
                        session['usuario_id'],
                        conversa_id,
                        mensagem_id,
                        token_metrics,
                        modelo=modelo
                    )

                    return jsonify({
                        'status': 'completed',
                        'response': resposta,
                        'mensagem_id': mensagem_id,
                        'token_metrics': token_metrics
                    })

        # Se o status for "failed" ou "expired", indicar claramente no retorno
        if run.status in ['failed', 'expired', 'cancelled']:

            return jsonify({
                'status': 'failed',
                'error': f'A execução foi interrompida com status: {run.status}'
            })

        return jsonify({'status': run.status})

    except Exception as e:

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
        contexto_tecnico = data.get('contexto_tecnico', '')

        usuario_id = session['usuario_id']
        client = OpenAI(api_key=get_api_key(usuario_id))

        # Criar thread e adicionar contexto
        thread_id = create_thread(client)
        if contexto_tecnico:
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=f"CONTEXTO TÉCNICO:\n{contexto_tecnico}"
            )

        # Salvar conversa no banco
        conversa_data = {
            "id_usuario": usuario_id,
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "data_inicio": datetime.now().isoformat()
        }

        response = supabase.table("conversas").insert(conversa_data).execute()
        return jsonify({
            'success': True,
            'conversa_id': response.data[0]['id'],
            'thread_id': thread_id
        })

    except Exception as e:
        print(f"Erro ao criar conversa: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


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


@app.route('/rag_assistant')
def rag_assistant():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    usuario_id = session['usuario_id']
    usuario_nome = session.get('usuario_nome', 'Usuário')
    is_admin = session.get('is_admin', False)

    # Set the RAG assistant ID
    assistant_id = "asst_LqpNV5KZlig3wHiaY7RaAofw"

    return render_template(
        'rag_troubleshooting.html',
        usuario_nome=usuario_nome,
        is_admin=is_admin,
        selected_assistant_id=assistant_id
    )


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)