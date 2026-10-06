# -*- coding: utf-8 -*-
"""
Manifiesto completo del catálogo Lumy (cortantes + rodillos texturizadores).
Generado a partir del relevamiento visual del catálogo Canva "Catalogo Lumy sep-2026".
Estructura: CORTANTES / RODILLOS -> lista de (codigo_categoria, nombre_categoria, [(codigo_item, nombre_item), ...])
"""

CORTANTES = [
    ("01", "Abecedario / Números", [
        ("01-01", "Número 1"), ("01-02", "Número 2"), ("01-03", "Número 3"), ("01-04", "Número 4"),
        ("01-05", "Número 5"), ("01-06", "Número 6"), ("01-07", "Número 7"), ("01-08", "Número 8"),
        ("01-09", "Número 9"), ("01-10", "Número 0"), ("01-11", "Letra A"), ("01-12", "Letra B"),
        ("01-13", "Letra C"), ("01-14", "Letra D"), ("01-15", "Letra E"),
    ]),
    ("02", "Animales de Granja", [
        ("02-01", "Vaca Cara"), ("02-02", "Caballo Cara"), ("02-03", "Chancho Cara"), ("02-04", "Pollito"),
        ("02-05", "Vaca Cuerpo"), ("02-06", "Caballo Cuerpo"), ("02-07", "Hipopótamo"), ("02-08", "Gallina"),
    ]),
    ("03", "Animales de Mar", [
        ("03-01", "Cola de Sirena"), ("03-02", "Pez"), ("03-03", "Concha / Vieira"),
        ("03-04", "Estrella de Mar"), ("03-05", "Pulpo"), ("03-06", "Caballito de Mar"),
    ]),
    ("04", "Animales de la Selva", [
        ("04-01", "León"), ("04-02", "Jirafa"), ("04-03", "Hipopótamo Cara"), ("04-04", "Mono"),
        ("04-05", "Elefante"), ("04-06", "Cabeza Animal de la Selva"),
    ]),
    ("05", "Baby Shower", [
        ("05-01", "Mamadera / Biberón"), ("05-02", "Huella de Pie Bebé"), ("05-03", "Sello Baby Shower"),
        ("05-04", "Chupete"), ("05-05", "Set Mini Baby Shower"), ("05-06", "Body de Bebé"),
        ("05-07", "Body de Bebé Modelo 2"),
    ]),
    ("06", "Barbie", [
        ("06-01", "Silueta Cabeza Barbie"), ("06-02", "Logo Barbie"),
    ]),
    ("07", "Bluey", [
        ("07-01", "Bluey Parada"), ("07-02", "Cachorro Bluey"), ("07-03", "Bluey Cara"),
    ]),
    ("08", "Brainrots", [
        ("08-01", "Personaje Viral 1"), ("08-02", "Personaje Viral 2"), ("08-03", "Personaje Viral 3"),
        ("08-04", "Personaje Viral 4"), ("08-05", "Personaje Viral 5"), ("08-06", "Personaje Viral 6"),
    ]),
    ("09", "Cactus", [
        ("09-01", "Cactus en Maceta"), ("09-02", "Llama"), ("09-03", "Cactus con Flor"),
        ("09-04", "Cactus Ancho"), ("09-05", "Cactus Redondo"), ("09-06", "Cactus con Flor Lateral"),
    ]),
    ("10", "Circo", [
        ("10-01", "Payaso"), ("10-02", "Carpa de Circo"), ("10-03", "Oso en Bicicleta"),
        ("10-04", "Payaso Colgante"), ("10-05", "Mago con Conejo en Galera"), ("10-06", "Elefante en Bicicleta"),
    ]),
    ("11", "Comunión", [
        ("11-01", "Paloma"), ("11-02", "Ángel"), ("11-03", "Cruz"), ("11-04", "Iglesia / Capilla"),
    ]),
    ("12", "Corazones", [
        ("12-01", "Corazones Entrelazados"), ("12-02", "Corazón Lunares"), ("12-03", "Corazón Vitral"),
        ("12-04", "Corazón Textura Nube"), ("12-05", "Corazón Lazo"), ("12-06", "Corazón Rostro"),
    ]),
    ("13", "Dinosaurios", [
        ("13-01", "Dino Alado Bebé"), ("13-02", "Dino Bebé Sentado"), ("13-03", "T-Rex"),
        ("13-04", "Dino Bebé Sentado 2"), ("13-05", "Dino Caminando"), ("13-06", "Dino Cara"),
    ]),
    ("14", "Disney", [
        ("14-01", "Minnie Cara"), ("14-02", "Moño Minnie"), ("14-03", "Castillo Disney"),
        ("14-04", "Mickey Cara"), ("14-05", "Mano de Mickey"), ("14-06", "Set Mini Mickey"),
    ]),
    ("15", "Emojis", [
        ("15-01", "Emoji Mano de Paz"), ("15-02", "Emoji Enamorado"), ("15-03", "Emoji Pensativo"),
        ("15-04", "Emoji Risa Lengua Afuera"), ("15-05", "Emoji Risa Carcajada"),
    ]),
    ("16", "Equipos de Fútbol", [
        ("16-01", "Escudo Fútbol 1"), ("16-02", "Escudo Fútbol 2"), ("16-03", "Escudo Fútbol 3"),
        ("16-04", "Escudo Boca Juniors"), ("16-05", "Escudo River Plate"),
    ]),
    ("17", "Espacio Exterior", [
        ("17-01", "Alien"), ("17-02", "Luna con Cara"), ("17-03", "Planeta Tierra"), ("17-04", "Astronauta"),
        ("17-05", "Estrella"), ("17-06", "Luna Creciente"), ("17-07", "Astronauta Flotando"),
        ("17-08", "Platillo Volador"), ("17-09", "Cohete"), ("17-10", "Saturno"), ("17-11", "Nave Espacial"),
        ("17-12", "Satélite"), ("17-13", "Estrella Fugaz"), ("17-14", "Ovni 2"), ("17-15", "Saturno 2"),
    ]),
    ("18", "Flores", [
        ("18-01", "Rosa"), ("18-02", "Flor 4 Pétalos"), ("18-03", "Flor con Hojas"), ("18-04", "Margarita / Girasol"),
    ]),
    ("19", "Formas", [
        ("19-01", "Círculo"), ("19-02", "Corazón"), ("19-03", "Trébol"), ("19-04", "Rectángulo"),
        ("19-05", "Rombo"), ("19-06", "Estrella"),
    ]),
    ("20", "Frozen", [
        ("20-01", "Elsa"), ("20-02", "Anna"), ("20-03", "Olaf"), ("20-04", "Copo de Nieve"),
    ]),
    ("21", "Gatos", [
        ("21-01", "Gato Sentado Silueta"), ("21-02", "Gato Caminando Silueta"), ("21-03", "Huella de Pata"),
        ("21-04", "Hello Kitty"), ("21-05", "Pusheen Marco"), ("21-06", "Pusheen en Canasta"),
        ("21-07", "Pusheen"), ("21-08", "Gato en Percha"),
    ]),
    ("22", "Gimnasio", [
        ("22-01", "8 con Corazón"), ("22-02", "Shaker"), ("22-03", "Brazo Bíceps"),
        ("22-04", "Mancuerna"), ("22-05", "Par de Mancuernas"),
    ]),
    ("23", "Granja de Zenón", [
        ("23-01", "Vaca Cara Granja de Zenón"), ("23-02", "Gallina"), ("23-03", "Chancho Cara"),
        ("23-04", "Granero"), ("23-05", "Personaje Granja de Zenón"), ("23-06", "Vaca Cuerpo Granja de Zenón"),
    ]),
    ("24", "Halloween", [
        ("24-01", "Calavera"), ("24-02", "Murciélago"), ("24-03", "Sombrero de Bruja"), ("24-04", "Hueso / Rama"),
        ("24-05", "Calabaza"), ("24-06", "Ataúd"), ("24-07", "Momia"), ("24-08", "Fantasma"), ("24-09", "Gato Negro"),
    ]),
    ("25", "Harry Potter", [
        ("25-01", "Reliquias de la Muerte"), ("25-02", "Sombrero Seleccionador"),
        ("25-03", "Anteojos con Rayo"), ("25-04", "Moneda Andén 9¾"),
    ]),
    ("26", "Lilo & Stitch", [
        ("26-01", "Stitch"), ("26-02", "Stitch y Angel"), ("26-03", "Stitch Hawaiano"),
        ("26-04", "Flor Hibisco"), ("26-05", "Texto Ohana"),
    ]),
    ("27", "Merlina", [
        ("27-01", "Mano (La Cosa)"), ("27-02", "Telaraña"), ("27-03", "Texto Merlina"),
        ("27-04", "Merlina Silueta"), ("27-05", "Merlina Cuerpo"), ("27-06", "Merlina Cara"),
    ]),
    ("28", "Minecraft", [
        ("28-01", "Bloque TNT"), ("28-02", "Bloque Pico"), ("28-03", "Creeper Cara"),
        ("28-04", "Personaje Minecraft"), ("28-05", "Creeper Cuerpo"), ("28-06", "Minero Minecraft"),
    ]),
    ("29", "Mundial", [
        ("29-01", "Messi"), ("29-02", "Escudo AFA"), ("29-03", "Cancha de Fútbol"),
        ("29-04", "Camiseta Selección"), ("29-05", "Copa Mundial Silueta"), ("29-06", "Botín de Fútbol"),
        ("29-07", "Copa Mundial"), ("29-08", "Pelota de Fútbol"),
    ]),
    ("30", "Música", [
        ("30-01", "Tambor"), ("30-02", "Saxofón"), ("30-03", "Xilófono"), ("30-04", "Guitarra Acústica"),
        ("30-05", "Guitarra Eléctrica"), ("30-06", "Piano"), ("30-07", "Micrófono"), ("30-08", "Violín"),
    ]),
    ("31", "Oficios", [
        ("31-01", "Auto de Policía"), ("31-02", "Gorro de Chef"), ("31-03", "Maletín de Herramientas"),
        ("31-04", "Excavadora"), ("31-05", "Delantal"), ("31-06", "Bombero"),
    ]),
    ("32", "Paw Patrol", [
        ("32-01", "Chase Cara"), ("32-02", "Skye Cara"), ("32-03", "Everest Cara"),
        ("32-04", "Marshall Cara"), ("32-05", "Rubble Cara"), ("32-06", "Zuma Cara"),
    ]),
    ("33", "Pelotas", [
        ("33-01", "Pelota Básquet"), ("33-02", "Pelota Béisbol"), ("33-03", "Pelota Fútbol"),
        ("33-04", "Pelota Deportiva"), ("33-05", "Pelota Rugby / Fútbol Americano"), ("33-06", "Pelota Vóley"),
    ]),
    ("34", "Peppa Pig", [
        ("34-01", "Peppa Cara"), ("34-02", "Papá Pig"), ("34-03", "Dinosaurio de George"),
        ("34-04", "Peppa Cuerpo"), ("34-05", "Peppa Pig 2"),
    ]),
    ("35", "Perros", [
        ("35-01", "Huella de Pata"), ("35-02", "Perro Silueta Labrador"), ("35-03", "Perro Silueta Sentado"),
        ("35-04", "Hueso"), ("35-05", "Perro Silueta Pequeño"), ("35-06", "Perro Silueta Pastor Alemán"),
        ("35-07", "Bulldog Francés Cara"),
    ]),
    ("36", "Piratas", [
        ("36-01", "Pirata Cara"), ("36-02", "Bandera Pirata"), ("36-03", "Barco Pirata"),
        ("36-04", "Medallón Pirata"), ("36-05", "Espada / Sable"),
    ]),
    ("37", "Power Rangers", [
        ("37-01", "Máscara Power Ranger Rojo"), ("37-02", "Máscara Power Ranger Azul"),
        ("37-03", "Máscara Power Ranger Amarillo"), ("37-04", "Máscara Power Ranger Rosa"),
        ("37-05", "Máscara Power Ranger Negro"), ("37-06", "Máscara Power Ranger Verde"),
    ]),
    ("38", "Princesas", [
        ("38-01", "Vestido Princesa"), ("38-02", "Princesa Cara con Corona"), ("38-03", "Corona"),
        ("38-04", "Vestido Princesa 2"), ("38-05", "Zapatito de Cristal"), ("38-06", "Carruaje"),
    ]),
    ("39", "Sirenas", [
        ("39-01", "Caballito de Mar"), ("39-02", "Estrella de Mar"), ("39-03", "Cola de Sirena"),
        ("39-04", "Concha / Vieira"), ("39-05", "Sirena Cuerpo Completo"),
    ]),
    ("40", "Sonic", [
        ("40-01", "Sonic Cara"), ("40-02", "Tails Cara"), ("40-03", "Knuckles Cara"), ("40-04", "Shadow Cara"),
    ]),
    ("41", "Superhéroes", [
        ("41-01", "Martillo de Thor"), ("41-02", "Máscara Batman"), ("41-03", "Logo Batman"),
        ("41-04", "Escudo Capitán América"), ("41-05", "Torso Hulk"), ("41-06", "Cara Hulk"),
        ("41-07", "Máscara Spiderman Mini"), ("41-08", "Máscara Iron Man"), ("41-09", "Máscara Spiderman"),
        ("41-10", "Logo Araña Spiderman"),
    ]),
    ("42", "Toy Story", [
        ("42-01", "Buzz Lightyear Cara"), ("42-02", "Woody Cara"), ("42-03", "Sombrero de Woody"),
        ("42-04", "Hamm"), ("42-05", "Texto Toy Story"), ("42-06", "Woody Cara 2"),
        ("42-07", "Buzz Lightyear Cuerpo"), ("42-08", "Alien Toy Story"), ("42-09", "Slinky"),
    ]),
    ("43", "Transportes", [
        ("43-01", "Auto Vocho"), ("43-02", "Auto de Carrera"), ("43-03", "Bandera a Cuadros"),
        ("43-04", "Motocicleta"), ("43-05", "Camioneta / Van"), ("43-06", "Avión"), ("43-07", "Auto Deportivo"),
        ("43-08", "Camión de Carga"), ("43-09", "Excavadora"), ("43-10", "Rueda con Llamas"),
        ("43-11", "Locomotora / Tren"),
    ]),
    ("44", "Zootopia", [
        ("44-01", "Serpiente"), ("44-02", "Cabra"), ("44-03", "Judy Hopps Cara"), ("44-04", "Judy Hopps Cuerpo"),
        ("44-05", "Nick Wilde Cara"), ("44-06", "Nick Wilde Cuerpo"), ("44-07", "Flash Perezoso"),
    ]),
]

RODILLOS = [
    ("1", "Animales", [
        ("1-1", "Delfines"), ("1-2", "Escamas"), ("1-3", "Gatos"), ("1-4", "Murciélagos"), ("1-5", "Pelaje"),
        ("1-6", "Perros"), ("1-7", "Pez 1"), ("1-8", "Pez 2"), ("1-9", "Pez 3"), ("1-10", "Piel de Caimán 1"),
        ("1-11", "Piel de Caimán 2"),
    ]),
    ("2", "Civilización", [
        ("2-1", "Carretera"), ("2-2", "Casas"), ("2-3", "Catacumbas"), ("2-4", "Egipto"),
        ("2-5", "Vecindario"), ("2-6", "Esqueletos"),
    ]),
    ("3", "Criaturas", [
        ("3-1", "Dinosaurios"), ("3-2", "Dinosaurios 2"), ("3-3", "Huesos de Dinosaurio"), ("3-4", "Dragones"),
    ]),
    ("4", "Festividades", [
        ("4-1", "San Valentín"), ("4-2", "San Valentín 2"), ("4-3", "San Valentín 3"), ("4-4", "San Valentín 4"),
        ("4-5", "San Valentín 5"), ("4-6", "San Patricio"), ("4-7", "Año Nuevo"), ("4-8", "Árbol de Navidad 2"),
        ("4-9", "Regalos"), ("4-10", "Árbol de Navidad"), ("4-11", "Navidad"), ("4-12", "Navidad 2"),
        ("4-13", "Pascua"), ("4-14", "Pascua 2"), ("4-15", "Halloween"), ("4-16", "Halloween 2"),
    ]),
    ("5", "Materiales", [
        ("5-1", "Tejido Realista"), ("5-2", "Tejido"), ("5-3", "Chapa Semilla de Melón"),
        ("5-4", "Metal Remachado 2"), ("5-5", "Metal Remachado 1"), ("5-6", "Piedra"), ("5-7", "Ladrillo 2"),
        ("5-8", "Ladrillo"), ("5-9", "Tejas"), ("5-10", "Veta de Madera"), ("5-11", "Veta de Madera 2"),
        ("5-12", "Veta de Madera 3"), ("5-13", "Llamas"), ("5-14", "Mimbre"), ("5-15", "Enrejado de Arco"),
        ("5-16", "Virutas 2"), ("5-17", "Virutas 1"),
    ]),
    ("6", "Naturaleza", [
        ("6-1", "Floral"), ("6-2", "Paz y Amor"), ("6-3", "Cuadros Florales"), ("6-4", "Juncos"),
        ("6-5", "Nieve 2"), ("6-6", "Nieve"), ("6-7", "Hoja de Cannabis"), ("6-8", "Cannabis 420"),
        ("6-9", "Hoja de Cannabis Chica"), ("6-10", "Cactus"), ("6-11", "Luna"),
    ]),
    ("7", "Texturas", [
        ("7-1", "Textura 1"), ("7-2", "Textura 2"), ("7-3", "Textura 3"), ("7-4", "Textura 4"),
        ("7-5", "Textura 5"), ("7-6", "Textura 6"), ("7-7", "Textura 7"), ("7-8", "Textura 8"),
        ("7-9", "Textura 9"), ("7-10", "Textura 10"), ("7-11", "Textura 11"), ("7-12", "Textura 12"),
        ("7-13", "Textura 13"), ("7-14", "Cuadros"), ("7-15", "Geométrico"), ("7-16", "Waffle"),
        ("7-17", "Bloques"),
    ]),
    ("8", "Varios", [
        ("8-1", "Vehículos de Construcción"), ("8-2", "Volquetes y Excavadoras"), ("8-3", "Símbolos del Zodíaco"),
        ("8-4", "Grullas Origami"), ("8-5", "Cocteles"), ("8-6", "Íconos Educativos"), ("8-7", "SixSeven"),
        ("8-8", "Escudos"), ("8-9", "Armas"),
    ]),
]

if __name__ == "__main__":
    n_cortantes = sum(len(items) for _, _, items in CORTANTES)
    n_rodillos = sum(len(items) for _, _, items in RODILLOS)
    print("Cortantes:", n_cortantes, "categorias:", len(CORTANTES))
    print("Rodillos:", n_rodillos, "categorias:", len(RODILLOS))
    print("Total:", n_cortantes + n_rodillos)
