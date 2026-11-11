"""RF34: gera dados 100% SINTÉTICOS de São Paulo para treino, teste e demonstração do robô.

- data/treino.csv           frases de TREINO do classificador
- data/teste_rotulado.csv   frases de TESTE (modelos de frase diferentes dos de treino) + dados
                            pessoais fictícios inseridos, para medir a anonimização
- ocorrências simuladas     no formato de CONTRATOS.md (seção E), gravadas na tabela `ocorrencia`
                            do SQLite local (reserva da API) + data/gabarito_ocorrencias.csv

Nomes, CPFs, telefones e e-mails são inventados. Texto informal: erros de digitação, sem acento,
caixa alta, abreviações. A geração é determinística (semente fixa) e a gravação é idempotente
(INSERT OR IGNORE): rodar de novo não duplica nem "ressuscita" ocorrências já enviadas.
"""
import random
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------------------------
# Modelos de frase. "treino" e "teste" são escritos de forma diferente de propósito.
# ---------------------------------------------------------------------------------------------
T = {
    "buraco_via": {
        "treino": ["Tem um buraco enorme no asfalto da {rua}.", "Buraco na pista perto da {local}, já estourou pneu de carro.",
                   "Cratera no meio da rua {rua}, perigoso pra moto.", "O asfalto afundou em frente ao número {num} da {rua}.",
                   "Precisa de tapa-buraco urgente na {rua}.", "A rua tá cheia de buraco depois da chuva.",
                   "Buraco fundo na esquina da {rua} com a avenida.", "O recapeamento abriu de novo e virou buraco.",
                   "Motoqueiro caiu por causa do buraco na {rua}.", "Asfalto todo esburacado no trecho da {local}."],
        "teste": ["Abriu uma vala no asfalto da {rua}, carro tá desviando pela contramão.",
                  "Pista com várias crateras perto da {local}, não dá pra passar de bicicleta.",
                  "Faz {dias} dias que tem um rombo no meio da rua e ninguém tapa.",
                  "O pavimento cedeu na frente do {num}, ficou um buracão.",
                  "Meu pneu furou num buraco escondido na poça da {rua}."]},
    "iluminacao_publica": {
        "treino": ["A lâmpada do poste da {rua} está queimada.", "Rua totalmente escura porque a luz do poste não acende.",
                   "Poste apagado há {dias} dias perto da {local}.", "Luz do poste piscando a noite inteira na {rua}.",
                   "Iluminação pública não funciona na praça do bairro.", "Tem poste com a luz acesa de dia na {rua}.",
                   "Trocar a lâmpada do poste em frente ao número {num}.", "A praça está sem iluminação, ninguém passa à noite.",
                   "Luminária do poste quebrada na {rua}.", "Os postes da rua inteira estão apagados."],
        "teste": ["Breu total na {rua} à noite, nenhuma luz da rua funcionando.",
                  "A luz da rua em frente à {local} não liga faz {dias} dias.",
                  "Lampada da via publica queimou e ficou tudo escuro na esquina.",
                  "Passagem escura e perigosa perto da {local}, falta luz de poste.",
                  "O refletor que ilumina a rua apagou e não voltou mais."]},
    "fio_energia_caido": {
        "treino": ["Fio de energia caído no chão da {rua} soltando faísca.", "Um fio de alta tensão arrebentou e está na calçada.",
                   "Cabo de luz caído e dando choque perto da {local}.", "Fio da rede elétrica partido no meio da rua.",
                   "Tem fio elétrico estalando e pegando fogo no poste da {rua}.", "Fio de energia rompido encostando no portão.",
                   "Cabo energizado caído depois da ventania.", "Fio da Enel arrebentado no chão, perigo de choque.",
                   "Faísca saindo do fio caído na esquina da {rua}.", "Fio elétrico solto no chão perto da {local}, crianças passam."],
        "teste": ["Tem um fio da luz no chão faiscando em frente ao {num}.",
                  "Arrebentou o cabo de energia com o vento e ficou caído na calçada da {rua}.",
                  "fio de energia estourou e ta soltando faisca no asfalto",
                  "Fiação elétrica partida pendurada até o chão perto da {local}, risco de choque.",
                  "Ouvi um estouro e agora tem fio de luz caído no meio da rua."]},
    "fiacao_telecom_solta": {
        "treino": ["Cabo de internet pendurado baixo na {rua}.", "Fio de telefone solto atravessando a rua.",
                   "Cabo de TV a cabo caído enrolado no poste.", "Fiação de telefonia solta e embolada perto da {local}.",
                   "Cabos de internet arrebentados pendurados na calçada.", "Fio de operadora pendurado na altura dos carros.",
                   "Emaranhado de fios de telecom soltos no poste da {rua}.", "Cabo de fibra óptica solto no chão.",
                   "Caminhão arrancou o cabo de internet e ficou pendurado.", "Fio preto de telefone solto balançando na {rua}."],
        "teste": ["Tem um monte de cabo de net largado no poste, quase encostando na cabeça.",
                  "O fio da operadora de internet ta caído na frente da {local}, sem energia nenhuma.",
                  "Cabeamento de telefonia abandonado enrolado na árvore da {rua}.",
                  "Cabos de comunicação pendurados baixo, caminhão vai arrancar.",
                  "Sobrou um rolo de cabo de TV solto pendurado no poste da esquina."]},
    "poste_danificado": {
        "treino": ["Poste inclinado ameaçando cair na {rua}.", "Carro bateu no poste e ele ficou rachado.",
                   "Poste de concreto quebrado na base perto da {local}.", "O poste está torto e a base está rachada.",
                   "Poste de madeira podre na {rua}.", "Poste com ferragem exposta e pedaço caindo.",
                   "Poste tombado depois da batida na esquina.", "Poste trincado no meio na {rua}.",
                   "O poste está balançando quando venta.", "Base do poste solta da calçada perto da {local}."],
        "teste": ["O poste em frente ao {num} entortou depois que um caminhão bateu.",
                  "Poste rachado de cima a baixo, dá medo de passar embaixo.",
                  "poste todo torto pendendo pro lado das casas na {rua}",
                  "A estrutura do poste de luz quebrou e tá escorada no muro.",
                  "Poste velho se desfazendo perto da {local}, caindo pedaço de concreto."]},
    "vazamento_agua": {
        "treino": ["Vazamento de água limpa na calçada da {rua}.", "Cano estourado jorrando água na rua.",
                   "Água vazando do hidrômetro em frente ao número {num}.", "Tem água brotando do asfalto há {dias} dias.",
                   "Vazamento da Sabesp desperdiçando muita água perto da {local}.", "A tubulação rompeu e a rua virou um rio de água limpa.",
                   "Água potável escorrendo sem parar no meio-fio.", "Registro da rua vazando água.",
                   "Cano da rede de água quebrado na {rua}.", "Vazamento de água na esquina, a pressão caiu nas casas."],
        "teste": ["Tá saindo água limpa de um buraco na calçada faz {dias} dias, desperdício.",
                  "A adutora estourou e a água jorra alto perto da {local}.",
                  "Água minando do chão da {rua} sem parar.",
                  "vazamento de agua na rua inteira e a torneira de casa sem pressao",
                  "Rompeu a tubulação de água em frente ao {num}, alagando a sarjeta com água limpa."]},
    "esgoto": {
        "treino": ["Esgoto a céu aberto na {rua}.", "Mau cheiro de esgoto saindo do bueiro.",
                   "Esgoto transbordando pela tampa do poço de visita.", "Esgoto voltando pelo ralo das casas da rua.",
                   "Vazamento de esgoto na calçada perto da {local}.", "Cheiro de fossa insuportável na {rua}.",
                   "Rede de esgoto entupida e retornando.", "Esgoto correndo pela sarjeta há {dias} dias.",
                   "Água suja e fedida saindo da tampa da Sabesp.", "Ligação de esgoto rompida na frente do número {num}."],
        "teste": ["Tem água preta com cheiro de cocô escorrendo na {rua}.",
                  "O esgoto da rua está subindo pelo vaso sanitário das casas.",
                  "Fedor de esgoto perto da {local}, ta escorrendo dejeto pela calçada.",
                  "Tampa de esgoto transbordando sujeira faz {dias} dias.",
                  "Esgoto vazando no córrego do lado das casas, mosquito pra todo lado."]},
    "cheiro_gas": {
        "treino": ["Cheiro forte de gás na {rua}.", "Sentimos cheiro de gás vazando perto da {local}.",
                   "Vazamento de gás encanado na calçada.", "Cheiro de gás muito forte saindo do chão.",
                   "Tubulação da Comgás com cheiro de gás.", "Odor de gás na esquina da {rua} desde cedo.",
                   "Parece que tem vazamento de gás na rua toda.", "Cheiro de gás perto do medidor do prédio.",
                   "Barulho de gás escapando na tubulação da rua.", "Cheiro de gás depois da obra na {rua}."],
        "teste": ["Tá um fedor de gás de cozinha na rua inteira, medo de explodir.",
                  "Moradores sentindo odor de gás encanado perto da {local}.",
                  "cheiro de gas forte saindo do bueiro da {rua}",
                  "Depois que a obra cavou a calçada ficou com cheiro de gás.",
                  "Chiado e cheiro de gás perto do registro em frente ao {num}."]},
    "calcada_quebrada": {
        "treino": ["Calçada toda quebrada na {rua}.", "A calçada está esburacada e idoso tropeçou.",
                   "Calçada levantada pela raiz da árvore.", "Piso da calçada solto em frente ao número {num}.",
                   "Calçada destruída, cadeirante não consegue passar.", "Calçada com degrau e buraco perto da {local}.",
                   "O passeio está quebrado e cheio de pedra solta.", "Falta pedaço da calçada na {rua}.",
                   "Calçada afundada na frente da casa.", "Calçada irregular e sem rampa de acessibilidade."],
        "teste": ["O passeio público em frente ao {num} está todo rachado e com pedaço faltando.",
                  "Minha mãe caiu na calçada esburacada da {rua}.",
                  "Lajotas soltas no passeio perto da {local}, cadeira de rodas não passa.",
                  "calcada toda detonada, tem que andar pela rua",
                  "Raiz levantou o piso do passeio e ficou um degrau enorme."]},
    "arvore_poda_queda": {
        "treino": ["Galho grande ameaçando cair na {rua}.", "Árvore caiu na calçada depois da chuva.",
                   "Precisa podar a árvore em frente ao número {num}.", "Árvore inclinada com risco de queda perto da {local}.",
                   "Galho seco quebrado pendurado na árvore.", "Árvore morta precisando de remoção.",
                   "Tronco caído bloqueando a rua.", "Árvore muito grande tampando a placa de rua.",
                   "Pedido de poda de árvore na praça.", "Árvore com cupim prestes a cair na {rua}."],
        "teste": ["Uma árvore tombou com o temporal e fechou a {rua}.",
                  "Os galhos da árvore estão quebrados e balançando em cima da calçada.",
                  "arvore enorme podre perto da {local} vai cair em alguem",
                  "Solicito a poda da copa da árvore da frente do {num}, galhos baixos demais.",
                  "Caiu um galhão em cima de um carro estacionado."]},
    "arvore_sobre_fiacao": {
        "treino": ["Galho de árvore encostado nos fios do poste.", "Árvore crescendo por cima da fiação elétrica.",
                   "Galhos enroscados na rede elétrica da {rua}.", "Árvore encostando nos fios e faltou luz.",
                   "Copa da árvore tomou conta da fiação do poste.", "Galho caiu em cima dos fios de energia.",
                   "Árvore raspando nos cabos de energia quando venta.", "Precisa poda porque a árvore pegou nos fios.",
                   "Galhos tocando a fiação perto da {local}.", "A árvore está apoiada na rede elétrica."],
        "teste": ["Os galhos da árvore estão enroscados nos cabos de luz e soltando estalos.",
                  "Galhada em cima dos fios do poste da {rua}, quando venta pisca a luz.",
                  "arvore entrelaçada na fiaçao eletrica perto da {local}",
                  "Um galho quebrou e ficou pendurado na fiação de energia.",
                  "A árvore cresceu e a rede de energia passa no meio dos galhos."]},
    "semaforo_defeito": {
        "treino": ["Semáforo apagado no cruzamento da {rua}.", "Farol de trânsito quebrado na esquina.",
                   "Semáforo piscando amarelo o dia todo.", "Sinaleiro com a luz vermelha queimada.",
                   "Semáforo de pedestre não funciona perto da {local}.", "Farol travado no vermelho há horas.",
                   "Semáforo virado para o lado errado depois da batida.", "Cruzamento sem semáforo funcionando, carros batendo.",
                   "Semáforo desligado na avenida.", "O tempo do semáforo de pedestre é muito curto."],
        "teste": ["O farol da esquina da {rua} tá todo apagado, ninguém sabe quem passa.",
                  "Sinal de trânsito com defeito perto da {local}, pisca sem parar.",
                  "Semaforo travado no verde para os dois lados, quase acidente.",
                  "O sinal pra pedestre não abre nunca na travessia da {local}.",
                  "Caiu a energia e o farol do cruzamento não voltou."]},
    "descarte_irregular": {
        "treino": ["Jogaram entulho na calçada da {rua}.", "Sofá velho abandonado na rua.",
                   "Descarte irregular de restos de obra perto da {local}.", "Montanha de entulho na esquina.",
                   "Colchão e móveis velhos jogados na calçada.", "Caçamba despejou entulho no terreno.",
                   "Pessoas descartando lixo de obra na praça.", "Ponto viciado de descarte de entulho na {rua}.",
                   "Pneus velhos jogados na beira do córrego.", "Restos de construção largados na calçada há {dias} dias."],
        "teste": ["Um caminhão despejou um monte de tijolo quebrado e terra na {rua}.",
                  "Largaram geladeira e guarda-roupa velhos perto da {local}.",
                  "entulho de reforma jogado na calcada, ninguem tira",
                  "Viraram a esquina num lixão de móveis e madeira velha.",
                  "Alguém deixou sacos de cimento, azulejo e restos de obra em frente ao {num}."]},
    "coleta_nao_realizada": {
        "treino": ["O caminhão de lixo não passou hoje na {rua}.", "Coleta de lixo não realizada há {dias} dias.",
                   "O lixeiro pulou a nossa rua na coleta.", "Coleta domiciliar atrasada no bairro.",
                   "A coleta seletiva não passou esta semana.", "Lixo das casas não foi recolhido no dia da coleta.",
                   "Caminhão do lixo não vem mais na {rua}.", "Faltou a coleta de lixo na terça e na quinta.",
                   "Os garis não recolheram o lixo da rua toda.", "A coleta do reciclável não aconteceu."],
        "teste": ["Faz {dias} dias que o caminhão do lixo não aparece na {rua}.",
                  "Os sacos estão na porta esperando a coleta que não veio.",
                  "O pessoal da coleta passou direto e não pegou o lixo das casas.",
                  "coleta do lixo domiciliar nao passou essa semana perto da {local}",
                  "Mudaram o horário da coleta e agora ela simplesmente não acontece."]},
    "lixo_acumulado": {
        "treino": ["Lixo acumulado na esquina da {rua}.", "Sacos de lixo espalhados pela calçada.",
                   "Monte de lixo atraindo ratos perto da {local}.", "Lixo amontoado na praça há {dias} dias.",
                   "Lixo espalhado na rua com mau cheiro.", "Acúmulo de lixo no canteiro central.",
                   "Lixo acumulado na beira do córrego.", "Sacolas de lixo rasgadas por cachorro na calçada.",
                   "Lixo jogado no terreno da esquina.", "Lixo se acumulando na frente da escola."],
        "teste": ["Tem uma pilha de sacolas de lixo apodrecendo na esquina da {rua}.",
                  "Lixarada espalhada pela calçada perto da {local}, cheio de barata.",
                  "Montoeira de lixo do lado do ponto de ônibus.",
                  "lixo acumulando no canto da praça faz {dias} dias",
                  "O lixo dos moradores fica amontoado no poste e os bichos espalham."]},
    "boca_de_lobo_entupida": {
        "treino": ["Boca de lobo entupida na {rua}.", "Bueiro cheio de lixo e folhas.",
                   "Boca de lobo tampada de terra perto da {local}.", "Bueiro entupido e a água não escoa.",
                   "Grade do bueiro obstruída por entulho.", "Galeria de águas pluviais entupida.",
                   "Boca de lobo sem tampa e cheia de lixo.", "Precisa limpar o bueiro da esquina.",
                   "Bueiro entupido em frente ao número {num}.", "Boca de leão entupida com garrafas."],
        "teste": ["O bueiro da esquina da {rua} tá tampado de lixo e a enxurrada não desce.",
                  "Boca de lobo obstruída com areia e garrafa pet perto da {local}.",
                  "bueru entupido de folha seca, quando chove empoça tudo",
                  "Pedido de limpeza das bocas de lobo da rua, todas entupidas.",
                  "A grelha de escoamento está bloqueada por sacos plásticos."]},
    "lixeira_publica": {
        "treino": ["Lixeira pública quebrada na {rua}.", "A lixeira da praça está transbordando.",
                   "Lixeira arrancada do poste perto da {local}.", "Falta lixeira na praça do bairro.",
                   "Lixeira pública cheia há {dias} dias.", "Cesto de lixo da rua quebrado.",
                   "A lixeirinha do ponto de ônibus caiu.", "Papeleira entortada na calçada.",
                   "Lixeira pública pegou fogo e derreteu.", "Pedido de instalação de lixeira na {rua}."],
        "teste": ["O cesto de lixo da calçada em frente ao {num} está todo amassado.",
                  "A papeleira do ponto de ônibus transbordou e o lixo tá caindo no chão.",
                  "lixeira da praça arrancaram e levaram embora",
                  "Precisamos de lixeiras na {rua}, o pessoal joga tudo no chão.",
                  "A lixeira pública perto da {local} está sem fundo."]},
    "varricao": {
        "treino": ["Rua sem varrição há {dias} dias.", "Os garis não varrem mais a {rua}.",
                   "Calçadas cheias de folhas, falta varrição.", "Pedido de varrição na praça.",
                   "Muita areia e sujeira acumulada na sarjeta.", "Falta limpeza das ruas do bairro.",
                   "A varrição da feira não foi feita.", "Rua imunda, precisa de varrição.",
                   "Sarjeta cheia de terra e folhas perto da {local}.", "Equipe de varrição não passa mais aqui."],
        "teste": ["Ninguém vem varrer a {rua} faz {dias} dias, folha e areia por todo lado.",
                  "Depois da feira a rua ficou suja e não teve limpeza.",
                  "sarjeta cheia de poeira e folha seca, falta gari varrendo",
                  "A calçada da {local} precisa de uma varrida, tá cheia de sujeira.",
                  "Pedimos a volta da varredura das ruas do bairro."]},
    "veiculo_abandonado": {
        "treino": ["Carro abandonado na {rua} há meses.", "Carcaça de veículo largada na rua.",
                   "Moto abandonada sem placa perto da {local}.", "Veículo com pneu murcho parado há meses.",
                   "Carro queimado abandonado na via.", "Caminhão velho abandonado na esquina.",
                   "Carro depenado parado em frente ao número {num}.", "Veículo abandonado juntando lixo e dengue.",
                   "Fusca abandonado ocupando vaga há um ano.", "Carro sem rodas largado na {rua}."],
        "teste": ["Tem uma carcaça de carro enferrujando na {rua} faz meses.",
                  "Deixaram um veículo sem placa e com vidro quebrado perto da {local}.",
                  "carro abandonado cheio de mato em volta, ninguem tira",
                  "Uma Kombi largada em frente ao {num}, pneus vazios, nunca sai do lugar.",
                  "Moto sem dono parada há semanas na calçada."]},
    "alagamento": {
        "treino": ["Rua alagada depois da chuva na {rua}.", "Alagamento na avenida, carros ilhados.",
                   "A rua alaga toda vez que chove perto da {local}.", "Água invadindo as casas com a enchente.",
                   "Ponto de alagamento na esquina da {rua}.", "Córrego transbordou e alagou a rua.",
                   "Rua virou um rio com a chuva.", "Enchente na rua, água na altura do joelho.",
                   "Alagamento no túnel, ninguém passa.", "A chuva forte deixou a rua debaixo d'água."],
        "teste": ["Com o temporal a água subiu e entrou nas casas da {rua}.",
                  "Enxurrada formou uma lagoa na avenida perto da {local}, carro boiando.",
                  "toda chuva a rua enche de agua e a gente fica ilhado",
                  "O córrego encheu e inundou o quarteirão inteiro.",
                  "A passagem subterrânea ficou inundada depois da chuva de ontem."]},
}

RUAS = ["Rua Augusta", "Av. Celso Garcia", "Rua Voluntários da Pátria", "Estrada do M'Boi Mirim",
        "Rua Teodoro Sampaio", "Av. Sapopemba", "Rua Cachoeira", "Rua dos Pinheiros", "Av. Inajar de Souza",
        "Rua Bresser", "Av. Jabaquara", "Rua Domingos de Morais"]
LOCAIS = ["escola", "creche", "UBS", "padaria", "igreja", "estação", "feira", "praça", "ponto de ônibus", "mercado"]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabriela", "Heitor", "Iara", "João", "Kelly", "Luiz"]
SOBRENOMES = ["Silva", "Souza", "Oliveira", "Pereira", "Lima", "Costa", "Ferreira", "Almeida", "Santos", "Rocha"]
PREFIXOS = ["", "", "", "Bom dia. ", "Boa tarde, ", "Oi, ", "Pfv, ", "Prefeitura, "]
SUFIXOS = ["", "", "", " Por favor resolvam.", " Já reclamei antes e nada.", " Isso é um perigo!",
           " Urgente!!", " Moro aqui há anos e nunca vi isso.", " Obrigado.", " Vcs podem ver isso?"]


def sem_acento(t):
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def com_erros(texto, rnd, taxa=0.06):
    """Simula erros de digitação: troca, omissão ou duplicação de letras em algumas palavras."""
    palavras = texto.split(" ")
    for i, p in enumerate(palavras):
        if len(p) > 4 and rnd.random() < taxa:
            j = rnd.randrange(1, len(p) - 1)
            op = rnd.choice(["troca", "omite", "duplica"])
            if op == "troca":
                p = p[:j] + p[j + 1] + p[j] + p[j + 2:]
            elif op == "omite":
                p = p[:j] + p[j + 1:]
            else:
                p = p[:j] + p[j] + p[j:]
            palavras[i] = p
    return " ".join(palavras)


def pessoa(rnd):
    nome = f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}"
    cpf = f"{rnd.randint(100, 999)}.{rnd.randint(100, 999)}.{rnd.randint(100, 999)}-{rnd.randint(10, 99)}"
    tel = rnd.choice([f"(11) 9{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}",
                      f"11 9{rnd.randint(1000, 9999)} {rnd.randint(1000, 9999)}",
                      f"119{rnd.randint(10000000, 99999999)}"])
    email = f"{sem_acento(nome).lower().replace(' ', '.')}{rnd.randint(1, 99)}@exemplo.com"
    return nome, cpf, tel, email


def gerar_texto(categoria, conjunto, rnd, com_pii=True):
    corpo = rnd.choice(T[categoria][conjunto]).format(
        rua=rnd.choice(RUAS), num=rnd.randint(10, 3000), dias=rnd.choice([2, 3, 5, 10, 15, 30]),
        local=rnd.choice(LOCAIS))
    pii = {"nome": "", "cpf": "", "telefone": "", "email": ""}
    prefixo = rnd.choice(PREFIXOS)
    if com_pii:
        nome, cpf, tel, email = pessoa(rnd)
        tipo = rnd.choice(["", "", "nome", "cpf", "tel", "email"])
        if tipo == "nome":
            prefixo, pii["nome"] = f"Olá, meu nome é {nome}. ", nome
        elif tipo == "cpf":
            prefixo, pii["nome"], pii["cpf"] = f"Sou {nome}, CPF {cpf}. ", nome, cpf
        elif tipo == "tel":
            prefixo, pii["telefone"] = f"Meu zap pra contato é {tel}. ", tel
        elif tipo == "email":
            prefixo, pii["email"] = f"Contato: {email}. ", email
    texto = prefixo + com_erros(corpo, rnd) + rnd.choice(SUFIXOS)
    r = rnd.random()
    if r < 0.20:
        texto = sem_acento(texto).lower()  # digitação informal
    elif r < 0.30:
        texto = texto.upper()
    return texto, pii


def gerar_conjunto(conjunto, n_por_cat, rnd, com_pii):
    linhas = []
    for cat in T:
        for _ in range(n_por_cat):
            texto, pii = gerar_texto(cat, conjunto, rnd, com_pii)
            linhas.append({"texto": texto, "categoria": cat, **pii})
    rnd.shuffle(linhas)
    return pd.DataFrame(linhas)


# ---------------------------------------------------------------------------------------------
# Ocorrências simuladas (formato CONTRATOS.md, seção E)
# ---------------------------------------------------------------------------------------------
def _uuid(rnd):
    return str(uuid.UUID(int=rnd.getrandbits(128), version=4))


def _protocolo(rnd, quando):
    return f"QR-{quando:%y%m%d}-{''.join(rnd.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))}"


def gerar_ocorrencias(base, rnd):
    """Retorna (lista de ocorrências, DataFrame gabarito)."""
    cats = list(T)
    agora = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    ocorrencias, gabarito = [], []

    def nova(cat_real, cat_final, descricao, status="pendente_envio", **extra):
        quando = agora - timedelta(minutes=rnd.randint(5, 60 * 48))
        sugerida = cat_final if rnd.random() < 0.85 else rnd.choice(cats)
        resp = base["categorias"].get(cat_final, {}).get("responsavel_id")
        oc = {"id": _uuid(rnd), "protocolo": _protocolo(rnd, quando),
              "criada_em": quando.strftime("%Y-%m-%dT%H:%M:%SZ"), "descricao": descricao,
              "lat": round(rnd.uniform(-23.75, -23.45), 5), "lon": round(rnd.uniform(-46.80, -46.40), 5),
              "categoria_sugerida": sugerida, "confianca": round(rnd.uniform(0.45, 0.97), 2),
              "categoria_final": cat_final, "responsavel_id": resp,
              "corrigida_pelo_cidadao": sugerida != cat_final, "status": status,
              "prioridade": rnd.randint(1, 5), "origem": rnd.choice(["cidadao"] * 4 + ["frota", "ambos"]),
              "grupo_duplicata_id": None, "foto_url": None}
        oc.update(extra)
        ocorrencias.append(oc)
        return oc

    # 1) 60 ocorrências válidas com a categoria certa (3 por categoria) -> esperado: enviar
    for cat in cats:
        for _ in range(3):
            texto, _ = gerar_texto(cat, "teste", rnd)
            oc = nova(cat, cat, texto)
            gabarito.append((oc["id"], cat, cat, "enviar", base["categorias"][cat]["responsavel_id"],
                             "válida, categoria correta"))
    # 2) 10 com categoria_final ERRADA (cidadão confirmou a sugestão errada) -> esperado: revisão
    for cat in rnd.sample(cats, 10):
        errada = rnd.choice([c for c in cats if c != cat])
        texto, _ = gerar_texto(cat, "teste", rnd)
        oc = nova(cat, errada, texto)
        gabarito.append((oc["id"], cat, errada, "revisao", "", "categoria_final não bate com a descrição"))
    # 3) 6 inválidas -> esperado: revisão (dado inválido)
    invalidas = [
        dict(descricao="", motivo="descrição vazia"),
        dict(descricao="ok", motivo="descrição curta"),
        dict(categoria_final="buraco", motivo="categoria fora da base (id antigo do contrato)"),
        dict(prioridade=9, motivo="prioridade fora de 1 a 5"),
        dict(id="OC-123", motivo="id não é UUID"),
        dict(origem="whatsapp", motivo="origem inválida"),
    ]
    for inv in invalidas:
        motivo = inv.pop("motivo")
        cat = rnd.choice(cats)
        texto, _ = gerar_texto(cat, "teste", rnd)
        dados = {"descricao": texto, **inv}
        cat_final = dados.pop("categoria_final", cat)
        oc = nova(cat, cat_final, dados.pop("descricao"), **dados)
        gabarito.append((oc["id"], cat, cat_final, "revisao", "", f"inválida: {motivo}"))
    # 4) 4 já enviadas em execução anterior -> esperado: ignorar (não aparecem como pendentes)
    for cat in rnd.sample(cats, 4):
        texto, _ = gerar_texto(cat, "teste", rnd)
        oc = nova(cat, cat, texto, status="enviada")
        gabarito.append((oc["id"], cat, cat, "ignorar", base["categorias"][cat]["responsavel_id"], "já enviada"))
    rnd.shuffle(ocorrencias)
    gab = pd.DataFrame(gabarito, columns=["id", "categoria_real", "categoria_final", "decisao_esperada",
                                          "responsavel_esperado", "observacao"])
    return ocorrencias, gab


def gravar_ocorrencias(caminho_db, ocorrencias):
    from src.db import COLUNAS_OCORRENCIA, conectar
    with conectar(caminho_db) as con:
        antes = con.execute("SELECT COUNT(*) FROM ocorrencia").fetchone()[0]
        con.executemany(
            f"INSERT OR IGNORE INTO ocorrencia ({','.join(COLUNAS_OCORRENCIA)}) "
            f"VALUES ({','.join('?' * len(COLUNAS_OCORRENCIA))})",
            [tuple(int(o[c]) if isinstance(o[c], bool) else o[c] for c in COLUNAS_OCORRENCIA) for o in ocorrencias])
        depois = con.execute("SELECT COUNT(*) FROM ocorrencia").fetchone()[0]
    return depois - antes


def main(dir_data=None, caminho_db=None):
    import json
    dir_data = Path(dir_data or RAIZ / "data")
    dir_data.mkdir(parents=True, exist_ok=True)
    base_json = json.loads((RAIZ / "data" / "base_quem_resolve.json").read_text(encoding="utf-8"))
    base = {"categorias": {c["id"]: c for c in base_json["categorias"]}}
    assert set(base["categorias"]) == set(T), "categorias do gerador e da base diferentes"

    gerar_conjunto("treino", 120, random.Random(2026), com_pii=True)[["texto", "categoria"]].to_csv(
        dir_data / "treino.csv", index=False)
    gerar_conjunto("teste", 15, random.Random(1102), com_pii=True).to_csv(
        dir_data / "teste_rotulado.csv", index=False)
    ocorrencias, gab = gerar_ocorrencias(base, random.Random(156))
    gab.to_csv(dir_data / "gabarito_ocorrencias.csv", index=False)
    novas = gravar_ocorrencias(Path(caminho_db or dir_data / "quem_resolve.db"), ocorrencias)
    resumo = {"treino": 120 * len(T), "teste_rotulado": 15 * len(T), "ocorrencias_geradas": len(ocorrencias),
              "ocorrencias_novas_no_banco": novas}
    print(f"Dados sintéticos: {resumo}")
    return resumo


if __name__ == "__main__":
    main()
