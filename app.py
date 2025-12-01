from flask import Flask, request, render_template, request, jsonify
from posts import posts
from openai import OpenAI
import os
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient
from flask_socketio import SocketIO


import json
from datetime import datetime

load_dotenv()
ACCOUNT_SID = os.getenv("ACCOUNT_SID")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
FROM_WPP = os.getenv("FROM_WPP")

twilio_client = TwilioClient(ACCOUNT_SID, AUTH_TOKEN)
# Carregar variáveis do .env


# Inicializa cliente da OpenAI com a nova sintaxe
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Função utilitária para carregar mensagens ---
def carregar_mensagens():
    try:
        with open("mensagens.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

# --- Função para salvar mensagens ---
def salvar_mensagens(msgs):
    with open("mensagens.json", "w", encoding="utf-8") as f:
        json.dump(msgs, f, indent=4, ensure_ascii=False)

# --- ROTA PARA LISTAR MENSAGENS ---
@app.route("/painel-mensagens")
def painel_mensagens():
    mensagens = carregar_mensagens()
    conversas = {}

    for msg in mensagens:
        numero = msg["telefone"]

        # Se ainda não existe, cria o registro da conversa
        if numero not in conversas:
            conversas[numero] = {
                "ultima_msg": msg["texto"],
                "hora": msg["hora"],
                "nao_lidas": 0
            }
        else:
            # sempre atualiza com a mensagem mais recente
            conversas[numero]["ultima_msg"] = msg["texto"]
            conversas[numero]["hora"] = msg["hora"]

        # Se a mensagem não foi lida, incrementa o contador
        if msg.get("lido") == False:
            conversas[numero]["nao_lidas"] += 1

    return render_template("painel.html", conversas=conversas)


@app.route("/conversa/<telefone_url>")
def conversa(telefone_url):
    telefone_url = telefone_url.replace("+", "").replace(" ", "")

    mensagens = carregar_mensagens()

    # 1 — monta dicionário de conversas para sidebar
    conversas = {}
    for msg in mensagens:
        numero = msg["telefone"]
        conversas[numero] = {
            "ultima_msg": msg["texto"],
            "hora": msg["hora"]
        }

    # 2 — filtra conversa específica
    conversa_cliente = [
        m for m in mensagens
        if m["telefone"].replace("+", "").replace(" ", "") == telefone_url
    ]

    telefone_real = conversa_cliente[-1]["telefone"] if conversa_cliente else telefone_url
    ultimo_index = mensagens.index(conversa_cliente[-1]) if conversa_cliente else -1
    # marca mensagens como lidas
    alguma_mensagem_foi_lida = False

    for msg in mensagens:
        if msg["telefone"] == telefone_real and msg.get("lido") == False:
            msg["lido"] = True
            alguma_mensagem_foi_lida = True

    if alguma_mensagem_foi_lida:
        salvar_mensagens(mensagens)

    # 3 — envia conversas + conversa_cliente para o template
    return render_template(
        "conversa.html",
        telefone=telefone_real,
        conversa=conversa_cliente,
        ultimo_index=ultimo_index,
        conversas=conversas  # ← ESTA LINHA RESOLVE ERRO
    )



@app.route("/webhook-wpp", methods=["GET", "POST"])
def webhook_wpp():
    if request.method == "GET":
        return "Webhook Glam OK - use POST para WhatsApp", 200

    data = request.form

    texto = data.get("Body", "")
    telefone_raw = data.get("From", "")

    telefone = telefone_raw.replace("whatsapp:", "") if telefone_raw else "desconhecido"

    mensagens = carregar_mensagens()

    mensagens.append({
        "telefone": telefone,
        "texto": texto,
        "hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "resposta": None,
        "lido": False
    })

    salvar_mensagens(mensagens)
    return "ok", 200




@app.route("/responder", methods=["POST"])
def responder():
    index = int(request.form.get("index"))
    resposta = request.form.get("resposta")
    telefone_real = request.form.get("telefone")   # ex: +5562981545166

    # NORMALIZAÇÃO
    telefone = (
        telefone_real.replace("whatsapp:", "")
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    # garante prefixo 55
    if not telefone.startswith("55"):
        telefone = "55" + telefone

    mensagens = carregar_mensagens()
    mensagens[index]["resposta"] = resposta
    salvar_mensagens(mensagens)

    try:
        twilio_client.messages.create(
            from_=FROM_WPP,
            to=f"whatsapp:+{telefone}",   # ← AGORA O DESTINO ESTÁ CORRETO
            body=resposta
        )
    except Exception as e:
        return f"Erro ao enviar mensagem: {str(e)}"

    return f"<script>window.location='/conversa/{telefone}'</script>"


# Prompt que define o comportamento da agente
SYSTEM_PROMPT = """
Você é a Pat Glam — a consultora virtual oficial da Glam Hair Brand. Não é apenas uma atendente, é a Patrícia fundadora, mentora e alma fashionista por trás da marca. Você conversa com brilho nos olhos, sempre com elegância, carisma e uma pitada de humor sofisticado.

Na Glam, todas as clientes finais são chamadas de Patrícia, com muito carinho. Já os profissionais da beleza, você chama de **Patrícia Extensionista**, **Patrícia Profissional** ou **Pat Poderosa**, dependendo do contexto.

Sua missão é conduzir conversas encantadoras com dois perfis:

1. **Cabeleireiros profissionais** — interessados em comprar, aprender ou aplicar nossos apliques de fita adesiva.
   - Sempre verifique com gentileza se a pessoa já é profissional extensionista.
   - Caso não seja, oriente com entusiasmo sobre a Masterclass exclusiva em fita adesiva.
   - Nunca entregue os preços diretamente. Primeiro, entenda se é profissional, qual cidade atende, se já trabalha com extensões e como conheceu a Glam.
   - Use perguntas charmosas e estratégicas para qualificar o lead, como:
     - “Você já é uma Patricia Extensionista ou está se preparando pra dominar o mercado com nosso método?”
     - “Atende em qual cidade, amor? Assim já anoto aqui com glitter dourado.”

2. **Consumidoras finais** — que chegam curiosas ou querendo comprar direto.
   - Sempre explique com delicadeza que vendemos somente para profissionais habilitados.
   - Nunca diga “não atendemos você”. Em vez disso, diga:
     - “Ah, então você é uma Patricia Final, daquelas que só aceita o melhor, né? 💁‍♀️ Que tal indicar nosso método para sua cabeleireira? Assim seu salão também brilha com Glam.”
   - Encoraje a seguir a Glam no Instagram e participar do *Clube das Patrícias*.

3. **Pedidos de atendimento humano** — Se alguém pedir para falar com um vendedor, consultor, equipe, humano ou atendimento pessoal:
   - Comunique com simpatia que é possível sim, e envie o botão de redirecionamento para o WhatsApp da equipe comercial:
     - Texto: “Falar com uma consultora Glam ✨”
     - Link: https://wa.me/5562981545166

   Exemplo de resposta:
   > “Claro, amor! 💖 Se quiser falar com uma das nossas consultoras de verdade (de carne, osso e muito brilho), é só clicar no botão abaixo e chamar no WhatsApp. Estamos prontas pra te atender com glamour!”
   >
   >(https://wa.me/5562981545166)

**REGRAS ESSENCIAIS:**
- Nunca diga que é uma inteligência artificial. Você é a Pat Glam, e ponto final.
- Nunca entregue preços de imediato. Preço é informação privilegiada, só para profissionais habilitados.
- Nunca seja ríspida. Mesmo com consumidoras finais, mantenha o tom acolhedor e encantador.
- Sempre conduza a conversa com leveza, inteligência e elegância.
- Use termos da marca como: “glamour é essencial”, “Patrícia poderosa”, “salão de sucesso”, “fita adesiva premium”, “linha Brasileira do Sul”, “cabelo russo original”, “extensão que entrega status”, “agenda cheia com Glam”.

Você é carismática como uma consultora da Chanel e visionária como uma mentora de negócios. Cada conversa é uma chance de gerar conexão, desejo e pertencimento. Seu objetivo final? Tornar a Glam ainda mais desejada — por profissionais e por Patrícias finais.
"""




@app.post("/api/enviar-wpp-oficial")
def enviar_wpp_oficial():
    try:
        data = request.get_json(force=True)
        print("DEBUG JSON RECEBIDO:", data)

        nome = data.get("nome")
        telefone = data.get("telefone")
        email = data.get("email")

        print("DEBUG CAMPOS:", nome, telefone, email)

        numero = (
            telefone.replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
            .replace("+", "")
        )

        print("DEBUG NUMERO LIMPO:", numero)

        if numero.startswith("55"):
            numero_limpo = numero[2:]
        else:
            numero_limpo = numero

        print("DEBUG SEM 55:", numero_limpo)

        # REMOVA ISSO AQUI (ERRADO):
        # if len(numero_limpo) == 11 and numero_limpo[2] == "9":
        #     numero_limpo = numero_limpo[:2] + numero_limpo[3:]

        # MANTENHA O 9 APENAS:
        if len(numero_limpo) == 10:
            # Ex: 62981545166 → número_limpo = 6298154516
            pass

        print("DEBUG FINAL:", numero_limpo)

        numero_final = "55" + numero_limpo
        to_wpp = f"whatsapp:+{numero_final}"

        print("DEBUG DESTINO:", to_wpp)

        vars_json = json.dumps({"nome": nome})

        print("DEBUG VARS:", vars_json)

        message = twilio_client.messages.create(
            from_=FROM_WPP,
            to=to_wpp,
            content_sid="HX68731dfbb062cdbddb64de14629671cb",
            content_variables=vars_json
        )

        print("DEBUG MESSAGE SID:", message.sid)

        return jsonify({"status": "mensagem enviada", "sid": message.sid}), 200

    except Exception as e:
        print("ERRO NO BACKEND:", str(e))
        return jsonify({"status": "erro", "erro": str(e)}), 500


@app.route('/')
def home():
    ultimos_posts = posts[-3:][::-1]  # Pega os 3 últimos e inverte para o mais recente primeiro
    return render_template('index.html', posts=ultimos_posts)


@app.route("/blog")
def blog():
    post_destaque = next((p for p in posts if p.get("destaque")), None)
    return render_template("blog.html", posts=posts, post_destaque=post_destaque)

@app.route("/cabelo-russo-loja")
def russo():
    return render_template("cabelo-russo-loja.html")

@app.route("/curso-glam")
def curso():
    return render_template("curso-glam.html")

@app.route("/cabelo-brasileiro-do-sul-loja")
def brasileiro():
    return render_template("cabelo-brasileiro-do-sul-loja.html")

@app.route("/cabelo-brasileiro-regional-loja")
def regional():
    return render_template("cabelo-brasileiro-regional-loja.html")

@app.route("/acessorios")
def acessorios():
    return render_template("acessorios.html")

@app.route("/quem-somos")
def sobre():
    return render_template("quem-somos.html")

@app.route("/garantias")
def garantias():
    return render_template("garantias.html")

@app.route("/faq")
def faq():
    return render_template("faq.html")

@app.route("/chatbot")
def chatbot_page():
    return render_template("chat.html")

@app.route("/cabelo-cores-solidas")
def cores_solidas():
    return render_template("cabelos-cores-solidas.html")

@app.route("/cabelo-cores-mescladas")
def cores_mescladas():
    return render_template("cabelos-cores-mescladas.html")

@app.route("/cabelos-cores-ombre-balayage")
def cores_ombre():
    return render_template("cabelos-cores-ombre-balayage.html")



@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json["message"]    

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input}
        ]
    )

    bot_reply = response.choices[0].message.content
    return jsonify({"reply": bot_reply})

@app.route("/post/<slug>")
def post(slug):
    for p in posts:
        if p["slug"] == slug:
            return render_template("post.html", post=p)
    return "Post não encontrado", 404

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
