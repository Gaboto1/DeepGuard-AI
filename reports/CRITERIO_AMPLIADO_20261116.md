# Criterio de adopción ampliado — fijado antes de medir

Escrito el 16 de noviembre de 2026, **antes** de entrenar ningún cabezal
candidato y antes de ver ninguna cifra de los conjuntos de confirmación. El
commit que lo introduce es la prueba de la fecha.

## Por qué hace falta ampliarlo

El criterio vigente (`scripts/decidir_adopcion.py`) decide mirando el conjunto
retenido del proyecto: LFW, ImageNet-val, FLUX y DALL·E 3. Hoy se midió el
sistema sobre fuentes que nunca había visto —fotografía auténtica de LAION y
Pexels e imágenes de 45 generadores, todas de OpenFake— y apareció un punto
ciego:

| | retenido del proyecto | fuentes externas |
|---|---|---|
| falsas alarmas sobre fotografía auténtica | 0,7 % | **38,7 %** * |
| IA señalada | 76,7 % | 89,9 % * |

\* a nivel del meta-ensemble, rama de imagen completa, sin reglas forenses
(`reports/_meta_vigente_externo.csv`). Es la cifra previa; la medición por la
vía de producción completa es la que decide y se hace sobre E2.

LFW e ImageNet son fotografía antigua, pequeña y muy comprimida, del mismo
estilo que las fuentes de entrenamiento (COCO, CelebA). El probe CLIP, que
lleva el 64 % del peso del cabezal principal, marca como IA más de la mitad de
la fotografía moderna que no vio (52,8 % en LAION, 68,2 % en Pexels por encima
de 0,70). El retenido no podía verlo, y un criterio que sólo mira el retenido
tampoco.

## Los dos conjuntos de confirmación

**E1 — el retenido del proyecto.** Sin cambios: 500 imágenes por fuente,
barajado con semilla 13, tramo `[0:500]`.

**E2 — material «en la calle».** El subconjunto `reddit` de OpenFake, shard
`test-00002-of-00005`: fotografías de subreddits de fotografía contra imágenes
de subreddits de generación por IA. No participa en ningún entrenamiento, ni
del probe ni de los cabezales.

Cada uno se parte en dos tramos disjuntos: **desarrollo**, donde se comparan
las variantes, y **confirmación**, que se mira una sola vez.

- E1-desarrollo: tramo `[500:900]` del barajado. E1-confirmación: `[0:500]`.
- E2-desarrollo: primera mitad del shard. E2-confirmación: segunda mitad.

## Las variantes, declaradas de antemano

| | cabezales | mezcla de ramas |
|---|---|---|
| V0 | vigentes | lineal (vigente) |
| V1 | vigentes | «o» en fotografía |
| V2 | reentrenados con fuentes externas | lineal |
| V3 | reentrenados con fuentes externas | «o» en fotografía |

Más un **control**: cabezales reentrenados *sin* las fuentes externas, para
poder atribuir el efecto a los datos y no al mero hecho de reentrenar.

No entran en esta ronda las variantes de la Regla 1: ya se midieron y se
descartaron (sección 12 del informe v4).

## La regla

**Paso A — elegir, sobre desarrollo.** Una variante es elegible si en
E1-desarrollo no activa ninguno de los dos vetos de siempre (falsas alarmas
+0,3 pt, AUC −0,005) y en E2-desarrollo no sube las falsas alarmas. Entre las
elegibles se elige la de menor error equilibrado en E2-desarrollo,
`(falsas alarmas + (100 − IA señalada)) / 2`; a igualdad, la de menos falsas
alarmas.

**Paso B — confirmar, una sola vez.** La variante elegida se adopta si y sólo
si:

1. En E1-confirmación no activa ningún veto: las falsas alarmas no suben más
   de 0,3 pt y el AUC no baja más de 0,005. Son los umbrales de
   `decidir_adopcion.py`, importados, no copiados.
2. Y mejora de forma medible en al menos uno de los dos conjuntos:
   - en E1, según la regla de siempre (IA señalada +1,0 pt, o estable con
     falsas alarmas −0,2 pt); **o**
   - en E2-confirmación, las falsas alarmas bajan al menos **5 puntos** y la
     IA señalada no baja más de **5 puntos**.

Si ninguna variante es elegible en el paso A, o la elegida no pasa el paso B,
no se adopta nada y se restaura lo que hubiera.

## Límites que quedan declarados

- **E2 tiene etiquetas ruidosas.** La clase la da el subreddit de origen. Una
  foto de un subreddit de fotografía puede estar muy retocada o ser un
  montaje; una imagen de un subreddit de IA puede estar reescalada o editada
  después. Las cifras sobre E2 son comparables entre variantes, pero no son
  una tasa de error limpia.
- **El tramo de desarrollo comparte fuentes con el de confirmación.** Los
  detectores no han visto ninguna, pero la lógica de fusión elegida deja de
  ser ciega a FLUX, DALL·E 3 y al material de Reddit.
- **Los umbrales de E2 (5 puntos) se fijan a priori**, a la vista sólo del
  orden de magnitud de la cifra previa de arriba, no de ningún resultado de
  las variantes.
