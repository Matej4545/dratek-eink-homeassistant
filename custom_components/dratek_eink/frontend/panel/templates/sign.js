// Everything about the "Cedule" (department sign) display template.
//
// The simplest thing a shelf display can be: a picture and a word. No entity,
// no integration, no data that can go stale - you type what the aisle is called,
// pick a glyph for it, and send it. Everything else in this catalog answers
// "what is happening right now"; this one answers "what is this place".

export const template = {
  catalog: {
    id: "sign",
    number: "31",
    category: "shop",
    title: "Cedule s ikonou",
    manualValues: true,
    // Nothing here is a reading, so the settings dialog drops the entity
    // pickers and their help text: two fields instead of a wall in front of
    // two words. See _renderTemplateVariableSetting.
    manualOnly: true,
    // Fourth element = the switch starts on. Without it the board would arrive
    // with no picture on it until the user found the setting.
    options: [[
      "icon",
      "Zobrazit ikonu",
      "Ikona na barevné ploše vlevo, popisek vpravo. Po odškrtnutí ikona zmizí a popisek se roztáhne přes celou ceduli.",
      true,
    ]],
    // POŘADÍ JE TRVALÉ. Klíč vazby je odvozený z indexu a popisku (viz
    // _templateVariableMeta), takže vložení proměnné doprostřed přepíše vazby
    // všech následujících na už nasazených displejích.
    variables: [
      ["shape-outline", "Ikona", "icon"],
      ["format-text", "Popisek"],
      ["palette", "Barva pozadí", "plate"],
    ],
  },
  prepared: true,
  setup: {
    summary: "Ikona na barevné ploše a popisek vedle ní. Obojí se vypisuje ručně, displej tedy nepotřebuje žádnou entitu ani integraci.",
    integrations: [],
    steps: [
      "V Nastavit klikněte u pole Ikona na dlaždici a vyberte ikonu z knihovny Designeru. Do pole pod knihovnou lze místo toho napsat název kterékoli MDI ikony bez předpony mdi: - třeba cart, fridge-outline nebo tools; seznam je na pictogrammers.com/library/mdi/.",
      "Do pole Popisek napište, jak se oddělení jmenuje.",
      "Barvu plochy pod ikonou vyberte v poli Barva pozadí. Přepínačem Zobrazit ikonu ceduli přepnete mezi obrázkem s popiskem a samotným popiskem přes celou plochu.",
    ],
    note: "Žlutá plocha na tříbarevném displeji vyjde černá - žlutý pigment tam neexistuje a přebarvit ji na červenou by vzalo červenou jako vaši vlastní volbu. Na černé i červené ploše se ikona vykreslí bíle, na žluté a bílé černě. Popisek se zalamuje po slovech a teprve když ani zalomený nestačí, zmenší se písmo - delší název oddělení tedy vyjde na víc řádků, ne přetečený.",
  },
  design: ({ v, option }) => {
    const board = {
      // The outlined cart rather than the filled one: at this size a solid
      // silhouette is a slab of ink, and the outline is also one of the icons
      // the offline test harness vendors, so the default draws everywhere.
      icon: v(0, "cart-outline"),
      text: v(1, "Nákupní oddělení"),
      plate: v(2, "yellow"),
      showIcon: option("icon"),
    };
    // Edge to edge in both orientations. The board used to keep a margin on a
    // tall panel so it read as a plate on paper; the plate is the thing that
    // reads, and a strip of white above and below it just made the sign
    // smaller.
    // pixelPerfect takes the page padding off: the plate is meant to run into
    // the panel's own edge, and a 6px white margin around it reads as a badly
    // cut sticker rather than as a design.
    return [{ sign: board, h: 1, pixelPerfect: true }];
  },
};
