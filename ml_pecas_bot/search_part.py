from ddgs import DDGS
import requests
from bs4 import BeautifulSoup


from ddgs import DDGS

def buscar_links(codigo):

    query = f"{codigo} site:mercadolivre.com.br"

    links = []

    with DDGS() as ddgs:

        resultados = ddgs.text(
            query,
            region="br-pt",
            max_results=10
        )

        for r in resultados:
            links.append(r["href"])

    return links


def extrair_dados(url):

    try:

        headers = {"User-Agent": "Mozilla/5.0"}

        response = requests.get(url, headers=headers, timeout=10)

        soup = BeautifulSoup(response.text, "html.parser")

        titulo = soup.title.string if soup.title else "N/A"

        imagens = []

        for img in soup.find_all("img"):

            src = img.get("src")

            if src and src.startswith("http"):
                imagens.append(src)

        return {
            "titulo": titulo,
            "imagens": imagens[:5]
        }

    except Exception as e:

        print("Erro ao acessar:", url)

        return None


def buscar_peca(codigo):

    print(f"\n🔎 Buscando peça: {codigo}\n")

    links = buscar_links(codigo)

    print("Links encontrados:", len(links))

    resultados = []

    for link in links[:5]:

        dados = extrair_dados(link)

        if dados:

            resultados.append({
                "url": link,
                "titulo": dados["titulo"],
                "imagens": dados["imagens"]
            })

    return resultados


if __name__ == "__main__":

    codigo = input("Digite o código da peça: ")

    dados = buscar_peca(codigo)

    for item in dados:

        print("\n----------------------------")
        print("URL:", item["url"])
        print("Título:", item["titulo"])

        print("Imagens:")

        for img in item["imagens"]:
            print(img)