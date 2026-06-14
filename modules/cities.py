import re

CITY_MAP = {
    # Tortosa area
    "tortosa": "Tortosa",
    "l'aldea": "L'Aldea", "aldea": "L'Aldea",
    "l'ametlla de mar": "L'Ametlla de Mar", "ametlla": "L'Ametlla de Mar",
    "l'ampolla": "L'Ampolla", "ampolla": "L'Ampolla",
    "el perelló": "El Perelló", "el perello": "El Perelló", "perello": "El Perelló",
    "deltebre": "Deltebre",
    "sant jaume d'enveja": "Sant Jaume d'Enveja", "sant jaume": "Sant Jaume d'Enveja",
    "amposta": "Amposta",
    "sant carles de la ràpita": "Sant Carles de la Ràpita", "la rapita": "Sant Carles de la Ràpita", "sant carles": "Sant Carles de la Ràpita",
    "alcanar": "Alcanar",
    "ulldecona": "Ulldecona",
    "la sénia": "La Sénia", "la senia": "La Sénia",
    "godall": "Godall",
    "mas de barberans": "Mas de Barberans",
    "freginals": "Freginals",
    "galera": "La Galera", "la galera": "La Galera",
    "masdenverge": "Masdenverge",
    "sant carles de la rapita": "Sant Carles de la Ràpita",
    "roquetes": "Roquetes",
    "jesús": "Jesús", "jesus": "Jesús",
    "xerta": "Xerta",
    "benifallet": "Benifallet",
    "rasquera": "Rasquera",
    "miravet": "Miravet",
    "móra d'ebre": "Móra d'Ebre", "mora d ebre": "Móra d'Ebre", "mora debre": "Móra d'Ebre",
    "móra la nova": "Móra la Nova", "mora la nova": "Móra la Nova",
    "ginestar": "Ginestar",
    "tivenys": "Tivenys",
    "aldover": "Aldover",
    "campredó": "Campredó", "campredo": "Campredó",
    "l'hospitalet de l'infant": "L'Hospitalet de l'Infant", "hospitalet infant": "L'Hospitalet de l'Infant",
    "miami platja": "Miami Platja", "miami playa": "Miami Platja",
    "vandellòs": "Vandellòs i l'Hospitalet", "vandellós": "Vandellòs i l'Hospitalet",
    "cambrils": "Cambrils",
    "salou": "Salou",
    "tarragona": "Tarragona",
    "reus": "Reus",
    "valls": "Valls",
    "montblanc": "Montblanc",
    "gandesa": "Gandesa",
    "bot": "Bot",
    "horta de sant joan": "Horta de Sant Joan",
    "arnes": "Arnes",
    "batea": "Batea",
    "corbera d'ebre": "Corbera d'Ebre",
    "la fatarella": "La Fatarella",
    "la pobla de massaluca": "La Pobla de Massaluca",
    "prat de comte": "Prat de Comte",
    "vilalba dels arcs": "Vilalba dels Arcs",
    "pinell de brai": "El Pinell de Brai",
    "benissanet": "Benissanet",
    "vinebre": "Vinebre",
    "la torre de l'espanyol": "La Torre de l'Espanyol",
    "riudoms": "Riudoms",
    "falset": "Falset",
    "pradell": "Pradell de la Teixeta",
    "bellmunt del priorat": "Bellmunt del Priorat",
    "gratallops": "Gratallops",
    "lloar": "El Lloar",
    "la bisbal de falset": "La Bisbal de Falset",
    "porrera": "Porrera",
    "cornudella": "Cornudella de Montsant",
    "la vilella alta": "La Vilella Alta",
    "la vilella baixa": "La Vilella Baixa",
    "ulldemolins": "Ulldemolins",
    "colldejou": "Colldejou",
}


def normalize(city: str) -> str:
    if not city:
        return ""
    key = city.lower().strip()
    key = re.sub(r"[-_]", " ", key)
    key = re.sub(r"\s+", " ", key)
    return CITY_MAP.get(key, city.strip().title())


def from_url_slug(slug: str) -> str:
    if not slug:
        return ""
    return normalize(slug.replace("-", " "))
