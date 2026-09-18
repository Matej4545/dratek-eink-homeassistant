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
      ["shape-outline", "Ikona"],
      ["format-text", "Popisek"],
    ],
  },
  prepared: true,
  setup: {
    summary: "Ikona na barevné ploše a popisek vedle ní. Obojí se vypisuje ručně, displej tedy nepotřebuje žádnou entitu ani integraci.",
    integrations: [],
    steps: [
      "V Nastavit vyplňte Ruční hodnotu u pole Ikona názvem MDI ikony bez předpony mdi: - například cart, fridge-outline nebo tools. Funguje kterákoli ikona z pictogrammers.com/library/mdi/.",
      "Do pole Popisek napište, jak se oddělení jmenuje.",
      "Přepínačem Zobrazit ikonu ceduli přepnete mezi obrázkem s popiskem a samotným popiskem přes celou plochu.",
    ],
    note: "Barevná plocha pod ikonou je žlutá na čtyřbarevných displejích a černá s bílou ikonou na tříbarevných - žlutá na nich neexistuje a červená plocha vedle červeného textu by soupeřila o pozornost. Popisek se automaticky zmenší, aby se vešel celý; delší název oddělení proto vyjde menším písmem, ne přetečený.",
  },
  design: ({ v, option, width, height }) => {
    const board = {
      // The outlined cart rather than the filled one: at this size a solid
      // silhouette is a slab of ink, and the outline is also one of the icons
      // the offline test harness vendors, so the default draws everywhere.
      icon: v(0, "cart-outline"),
      text: v(1, "Nákupní oddělení"),
      showIcon: option("icon"),
    };
    // A tall panel gets a margin so the board reads as a plate on the paper
    // rather than as the panel's own edge; a small landscape tag has no such
    // room to give away and fills edge to edge.
    if (height > width) return [
      { gap: true, h: 0.06 },
      { sign: board, h: 0.88 },
      { gap: true, h: 0.06 },
    ];
    return [{ sign: board, h: 1 }];
  },
};
