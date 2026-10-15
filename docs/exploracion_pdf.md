# Exploración de PDF y elección del método de extracción

Estado: **método aún sin decidir** (`config.toml → bienes_rentas.metodo_extraccion` vacío).
Medido el 2026-10-15 con 4 PDF de `docbienes` + el BOCG-15-D-591.

## Qué son los PDF
- **docbienes** (un PDF por diputado y declaración): 5 páginas, escaneo puro (CCITT 1 bit, 2480×3507,
  300 ppi), **sin capa de texto** (solo la firma FNMT y un sello `C.DIP nº fecha`).
  Formulario rellenado a ordenador (texto impreso, no manuscrito) y aplanado a imagen.
- **BOCG-15-D-591** (Serie D, 42 págs., 25/09/2026): págs. 1–3 y 19+ con texto limpio; págs. 4–18 son
  formularios escaneados con una capa de texto OCR **corrupta** (`DEcLARAcTórut DE BTENES y RENTAS`,
  `DE2O23`). Contiene declaraciones registradas el 15/09/2026, la misma fecha que las modificaciones
  `001` de docbienes: **docbienes ya cubre lo que publica el BOCG**.
- El formulario incluye **rentas percibidas** (págs. 1): salario, dividendos, intereses, otras, cuota IRPF.
  xerraires no las extrae.
- Algunos formularios escriben el decimal con apóstrofo (`756.715'12`); `parse_importe_es` lo admite.

## Cobertura descubierta (fichas de congreso.es, XV)
429 declaraciones de 349 diputados: 350 iniciales (`000`), 79 modificaciones (`001`, de 71 diputados,
2023-08 → 2026-09), 0 finales (`002`). El `id` de la ruta docbienes ≠ `codParlamentario`.

## Tesseract 5.3.4 (`-l spa`, 300 ppi, págs. 2–4) frente a la referencia xerraires
Reproducir: `PYTHONPATH=src python -I tools/ocr_eval.py <pdf> <cod> <dir>`.

| cod | importes hallados | palabras de descripción |
|---|---|---|
| 12 | 16/17 | 153/153 |
| 281 | 4/5 | 101/101 |
| 182 | 9/9 | 168/169 |
| **total** | **29/31 (94 %)** | |

Con `--psm 4` (mejor que `--psm 6`: 65 % en el cod 12). ~3–4 s por página.
Los 2 fallos: uno de formato (`56 .419€`, cifra bien leída con un espacio colado) y uno de **dígitos**
(`195.005'79` leído como `185.00578`, comprobado contra la imagen). Este último es silencioso: el dato
parece válido. **Limitaciones de la medida:** n=3 diputados (los de más bienes), la referencia nació de
Tesseract + revisión manual (sesgo a favor de Tesseract), "hallado" = aparece en algún sitio del texto
(no mide a qué fila pertenece), no hay manuscritos.

## Lectura directa por visión (leída por Claude en esta sesión, no vía API)
Tabla de deudas del cod 12 (5 filas × 2 importes) + 3 importes de valores del cod 281: **13/13 correctos**,
coincidentes con Tesseract y con la referencia salvo `195.005'79`. n minúsculo: indicativo, no estadístico.
La referencia de xerraires tiene descripciones desordenadas (`PRÉSTAMO INMUEBLE) 1- HIPOTECARIO…`).

## Coste estimado de visión vía API (sin medir: no hay clave en esta sesión)
Supuestos: ~2,3 k tokens de entrada por página (resize a ~1568 px de lado mayor), 5 págs. + prompt ≈ 13 k
entrada y ≈ 4 k salida por declaración; 429 declaraciones. Precios de la tabla de modelos (2026-10-06).

| Modelo | $/MTok ent./sal. | ≈ total | con Batch (−50 %) |
|---|---|---|---|
| Haiku 5.5 | 0,10 / 0,50 | ≈ 1,4 $ | ≈ 0,7 $ |
| Sonnet 5.5 | 2 / 10 | ≈ 28 $ | ≈ 14 $ |
| Opus 5.5 | 4 / 20 | ≈ 56 $ | ≈ 28 $ |

Tesseract: 0 $, ≈ 20 s por declaración (≈ 2,4 h en serie, menos en paralelo).
