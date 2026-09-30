// Emoji shortcode rendering.
//
// Block content always stores the literal `:shortcode:` text — nothing
// in the save path rewrites it to a unicode emoji. That keeps content
// portable (grep for "grimacing" and you find it), keeps the
// render-emoji user setting reversible, and keeps block content free of
// ZWJ sequences / skin-tone modifiers / variation selectors that would
// otherwise make naive string slicing in the editor misbehave.
//
// Substitution happens here, at display time only.
(function () {
  // Curated map of the shortcodes people actually type, Discord/GitHub
  // spellings where the two agree. Deliberately not the full ~1900-entry
  // unicode set: this ships in the page (no CDN round-trip, works in the
  // installed PWA) so it's kept to a size that costs nothing to parse.
  const SHORTCODES = {
    // --- smileys ---
    grinning: "😀",
    smiley: "😃",
    smile: "😄",
    grin: "😁",
    laughing: "😆",
    satisfied: "😆",
    sweat_smile: "😅",
    rofl: "🤣",
    joy: "😂",
    slightly_smiling_face: "🙂",
    upside_down_face: "🙃",
    wink: "😉",
    blush: "😊",
    innocent: "😇",
    smiling_face_with_three_hearts: "🥰",
    heart_eyes: "😍",
    star_struck: "🤩",
    kissing_heart: "😘",
    kissing: "😗",
    relaxed: "☺️",
    kissing_closed_eyes: "😚",
    yum: "😋",
    stuck_out_tongue: "😛",
    stuck_out_tongue_winking_eye: "😜",
    zany_face: "🤪",
    stuck_out_tongue_closed_eyes: "😝",
    money_mouth_face: "🤑",
    hugs: "🤗",
    hand_over_mouth: "🤭",
    shushing_face: "🤫",
    thinking: "🤔",
    zipper_mouth_face: "🤐",
    raised_eyebrow: "🤨",
    neutral_face: "😐",
    expressionless: "😑",
    no_mouth: "😶",
    smirk: "😏",
    unamused: "😒",
    roll_eyes: "🙄",
    grimace: "😬",
    grimacing: "😬",
    lying_face: "🤥",
    relieved: "😌",
    pensive: "😔",
    sleepy: "😪",
    drooling_face: "🤤",
    sleeping: "😴",
    mask: "😷",
    face_with_thermometer: "🤒",
    face_with_head_bandage: "🤕",
    nauseated_face: "🤢",
    vomiting_face: "🤮",
    sneezing_face: "🤧",
    hot_face: "🥵",
    cold_face: "🥶",
    woozy_face: "🥴",
    dizzy_face: "😵",
    exploding_head: "🤯",
    cowboy_hat_face: "🤠",
    partying_face: "🥳",
    sunglasses: "😎",
    nerd_face: "🤓",
    monocle_face: "🧐",
    confused: "😕",
    worried: "😟",
    slightly_frowning_face: "🙁",
    frowning_face: "☹️",
    open_mouth: "😮",
    hushed: "😯",
    astonished: "😲",
    flushed: "😳",
    pleading_face: "🥺",
    frowning: "😦",
    anguished: "😧",
    fearful: "😨",
    cold_sweat: "😰",
    disappointed_relieved: "😥",
    cry: "😢",
    sob: "😭",
    scream: "😱",
    confounded: "😖",
    persevere: "😣",
    disappointed: "😞",
    sweat: "😓",
    weary: "😩",
    tired_face: "😫",
    yawning_face: "🥱",
    triumph: "😤",
    rage: "😡",
    angry: "😠",
    cursing_face: "🤬",
    smiling_imp: "😈",
    imp: "👿",
    skull: "💀",
    skull_and_crossbones: "☠️",
    poop: "💩",
    clown_face: "🤡",
    ghost: "👻",
    alien: "👽",
    space_invader: "👾",
    robot: "🤖",
    jack_o_lantern: "🎃",

    // --- gestures / people ---
    wave: "👋",
    raised_back_of_hand: "🤚",
    raised_hand: "✋",
    vulcan_salute: "🖖",
    ok_hand: "👌",
    pinched_fingers: "🤌",
    pinching_hand: "🤏",
    v: "✌️",
    crossed_fingers: "🤞",
    love_you_gesture: "🤟",
    metal: "🤘",
    call_me_hand: "🤙",
    point_left: "👈",
    point_right: "👉",
    point_up_2: "👆",
    middle_finger: "🖕",
    point_down: "👇",
    point_up: "☝️",
    thumbsup: "👍",
    "+1": "👍",
    thumbsdown: "👎",
    "-1": "👎",
    fist: "✊",
    facepunch: "👊",
    punch: "👊",
    fist_left: "🤛",
    fist_right: "🤜",
    clap: "👏",
    raised_hands: "🙌",
    open_hands: "👐",
    palms_up_together: "🤲",
    handshake: "🤝",
    pray: "🙏",
    writing_hand: "✍️",
    muscle: "💪",
    brain: "🧠",
    eyes: "👀",
    facepalm: "🤦",
    face_palm: "🤦",
    person_facepalming: "🤦",
    shrug: "🤷",
    person_shrugging: "🤷",
    person_raising_hand: "🙋",
    person_gesturing_no: "🙅",
    person_gesturing_ok: "🙆",
    person_bowing: "🙇",
    person_tipping_hand: "💁",
    dancer: "💃",
    man_dancing: "🕺",
    walking: "🚶",
    running: "🏃",
    baby: "👶",
    ok_woman: "🙆‍♀️",
    no_good: "🙅",

    // --- hearts / symbols ---
    heart: "❤️",
    orange_heart: "🧡",
    yellow_heart: "💛",
    green_heart: "💚",
    blue_heart: "💙",
    purple_heart: "💜",
    black_heart: "🖤",
    white_heart: "🤍",
    brown_heart: "🤎",
    broken_heart: "💔",
    two_hearts: "💕",
    sparkling_heart: "💖",
    heartpulse: "💗",
    cupid: "💘",
    gift_heart: "💝",
    hearts: "♥️",
    exclamation: "❗",
    question: "❓",
    bangbang: "‼️",
    warning: "⚠️",
    no_entry: "⛔",
    white_check_mark: "✅",
    heavy_check_mark: "✔️",
    x: "❌",
    negative_squared_cross_mark: "❎",
    recycle: "♻️",
    infinity: "♾️",
    100: "💯",
    anger: "💢",
    boom: "💥",
    collision: "💥",
    dizzy: "💫",
    sweat_drops: "💦",
    dash: "💨",
    hole: "🕳️",
    speech_balloon: "💬",
    thought_balloon: "💭",
    zzz: "💤",

    // --- objects / work ---
    fire: "🔥",
    sparkles: "✨",
    star: "⭐",
    star2: "🌟",
    zap: "⚡",
    rainbow: "🌈",
    sunny: "☀️",
    cloud: "☁️",
    snowflake: "❄️",
    umbrella: "☔",
    ocean: "🌊",
    moon: "🌙",
    earth_americas: "🌎",
    rocket: "🚀",
    bulb: "💡",
    computer: "💻",
    desktop_computer: "🖥️",
    keyboard: "⌨️",
    iphone: "📱",
    floppy_disk: "💾",
    cd: "💿",
    printer: "🖨️",
    camera: "📷",
    tv: "📺",
    telephone: "☎️",
    battery: "🔋",
    electric_plug: "🔌",
    mag: "🔍",
    lock: "🔒",
    unlock: "🔓",
    key: "🔑",
    hammer: "🔨",
    wrench: "🔧",
    nut_and_bolt: "🔩",
    gear: "⚙️",
    link: "🔗",
    paperclip: "📎",
    scissors: "✂️",
    pencil2: "✏️",
    memo: "📝",
    book: "📖",
    books: "📚",
    bookmark: "🔖",
    page_facing_up: "📄",
    clipboard: "📋",
    calendar: "📅",
    date: "📅",
    chart_with_upwards_trend: "📈",
    chart_with_downwards_trend: "📉",
    bar_chart: "📊",
    file_folder: "📁",
    open_file_folder: "📂",
    package: "📦",
    inbox_tray: "📥",
    outbox_tray: "📤",
    email: "📧",
    bell: "🔔",
    no_bell: "🔕",
    loudspeaker: "📢",
    mega: "📣",
    hourglass: "⌛",
    hourglass_flowing_sand: "⏳",
    watch: "⌚",
    alarm_clock: "⏰",
    stopwatch: "⏱️",
    money_with_wings: "💸",
    moneybag: "💰",
    credit_card: "💳",
    gem: "💎",
    trophy: "🏆",
    medal_sports: "🏅",
    dart: "🎯",
    game_die: "🎲",
    video_game: "🎮",
    art: "🎨",
    musical_note: "🎵",
    headphones: "🎧",
    guitar: "🎸",
    microphone: "🎤",
    clapper: "🎬",
    balloon: "🎈",
    tada: "🎉",
    confetti_ball: "🎊",
    gift: "🎁",
    christmas_tree: "🎄",
    crown: "👑",
    tophat: "🎩",
    eyeglasses: "👓",
    briefcase: "💼",
    house: "🏠",
    office: "🏢",
    hospital: "🏥",
    bank: "🏦",
    school: "🏫",
    construction: "🚧",
    car: "🚗",
    taxi: "🚕",
    bus: "🚌",
    ambulance: "🚑",
    fire_engine: "🚒",
    bike: "🚲",
    airplane: "✈️",
    ship: "🚢",
    anchor: "⚓",
    train: "🚆",
    traffic_light: "🚥",

    // --- food ---
    coffee: "☕",
    tea: "🍵",
    beer: "🍺",
    beers: "🍻",
    wine_glass: "🍷",
    cocktail: "🍸",
    tropical_drink: "🍹",
    champagne: "🍾",
    tumbler_glass: "🥃",
    cup_with_straw: "🥤",
    pizza: "🍕",
    hamburger: "🍔",
    fries: "🍟",
    hotdog: "🌭",
    taco: "🌮",
    burrito: "🌯",
    popcorn: "🍿",
    bread: "🍞",
    cheese: "🧀",
    egg: "🥚",
    bacon: "🥓",
    poultry_leg: "🍗",
    meat_on_bone: "🍖",
    spaghetti: "🍝",
    ramen: "🍜",
    sushi: "🍣",
    rice: "🍚",
    curry: "🍛",
    salad: "🥗",
    apple: "🍎",
    green_apple: "🍏",
    banana: "🍌",
    watermelon: "🍉",
    grapes: "🍇",
    strawberry: "🍓",
    peach: "🍑",
    cherries: "🍒",
    lemon: "🍋",
    avocado: "🥑",
    eggplant: "🍆",
    hot_pepper: "🌶️",
    corn: "🌽",
    carrot: "🥕",
    broccoli: "🥦",
    cake: "🍰",
    birthday: "🎂",
    cookie: "🍪",
    doughnut: "🍩",
    chocolate_bar: "🍫",
    candy: "🍬",
    lollipop: "🍭",
    ice_cream: "🍨",
    honey_pot: "🍯",

    // --- animals / nature ---
    dog: "🐶",
    cat: "🐱",
    mouse: "🐭",
    hamster: "🐹",
    rabbit: "🐰",
    fox_face: "🦊",
    bear: "🐻",
    panda_face: "🐼",
    koala: "🐨",
    tiger: "🐯",
    lion: "🦁",
    cow: "🐮",
    pig: "🐷",
    frog: "🐸",
    monkey_face: "🐵",
    see_no_evil: "🙈",
    hear_no_evil: "🙉",
    speak_no_evil: "🙊",
    chicken: "🐔",
    penguin: "🐧",
    bird: "🐦",
    duck: "🦆",
    owl: "🦉",
    bat: "🦇",
    wolf: "🐺",
    horse: "🐴",
    unicorn: "🦄",
    bee: "🐝",
    bug: "🐛",
    butterfly: "🦋",
    snail: "🐌",
    spider: "🕷️",
    turtle: "🐢",
    snake: "🐍",
    lizard: "🦎",
    octopus: "🐙",
    squid: "🦑",
    shrimp: "🦐",
    fish: "🐟",
    tropical_fish: "🐠",
    dolphin: "🐬",
    whale: "🐳",
    shark: "🦈",
    crocodile: "🐊",
    elephant: "🐘",
    seedling: "🌱",
    evergreen_tree: "🌲",
    deciduous_tree: "🌳",
    palm_tree: "🌴",
    cactus: "🌵",
    herb: "🌿",
    four_leaf_clover: "🍀",
    maple_leaf: "🍁",
    fallen_leaf: "🍂",
    leaves: "🍃",
    mushroom: "🍄",
    tulip: "🌷",
    rose: "🌹",
    sunflower: "🌻",
    blossom: "🌼",
    cherry_blossom: "🌸",
  };

  // Shortcode names are `[a-z0-9_+-]` — the `+`/`-` are for :+1: / :-1:.
  // Anything matching the shape but absent from the map is left exactly
  // as typed.
  const SHORTCODE_RE = /:([a-z0-9_+-]{1,32}):/gi;

  // The opening colon has to start a word. Matching the shape alone
  // isn't enough: `x:name:y` would hit too, and enough of those names
  // are real shortcodes to wreck ordinary text — pasted lint output
  // ("app.py:100:8" -> "app.py💯8"), a `key::value` block property, a
  // colon-namespaced identifier ("cache:key:ttl" -> "cache🔑ttl"). In
  // Page.formatContentWithTags the substitution runs ahead of the URL
  // linkifier, so a mangled path ends up inside the href, not just the
  // link text.
  const WORDISH_RE = /[\w:]/;

  const hasOwn = Object.prototype.hasOwnProperty;

  // `previousEnd` is the end offset of the last substitution. A run of
  // shortcodes shares colons — the second `:` of `:smile::smile:` opens
  // the second one — so a match butting straight up against the last
  // emoji is allowed through even though a colon precedes it.
  function startsAWord(source, offset, previousEnd) {
    if (offset === 0 || offset === previousEnd) return true;
    return !WORDISH_RE.test(source.charAt(offset - 1));
  }

  const brainspreadEmoji = {
    SHORTCODES,

    // isEnabled() runs once per block per render, so the parsed value is
    // cached against the raw localStorage string. Comparing the string
    // is cheap and self-invalidating — login, logout, and a settings
    // save all rewrite `user`, so there's no cache to remember to bust.
    _rawUser: undefined,
    _enabled: true,
    // Set by callers with no logged-in user (the public share page,
    // which follows the page owner's preference instead).
    _override: null,

    isEnabled() {
      if (this._override !== null) return this._override;
      let raw = null;
      try {
        raw = window.localStorage ? localStorage.getItem("user") : null;
      } catch (_) {
        // localStorage throws in some private-browsing modes.
        raw = null;
      }
      if (raw !== this._rawUser) {
        this._rawUser = raw;
        let user = null;
        try {
          user = raw ? JSON.parse(raw) : null;
        } catch (_) {
          user = null;
        }
        // Default on — a user who has never touched the setting and the
        // logged-out case both get emoji.
        this._enabled = user ? user.render_emoji !== false : true;
      }
      return this._enabled;
    },

    setEnabled(enabled) {
      this._override = !!enabled;
    },

    /**
     * Replace known `:shortcode:` sequences with their emoji. Unknown
     * shortcodes are returned verbatim. Does no HTML escaping — callers
     * run this on raw text before their own escaping/markdown pass.
     */
    replaceShortcodes(text) {
      if (!text || text.indexOf(":") === -1) return text;
      const source = String(text);
      let previousEnd = -1;
      return source.replace(SHORTCODE_RE, (match, name, offset) => {
        if (!startsAWord(source, offset, previousEnd)) return match;
        const key = name.toLowerCase();
        // hasOwnProperty, not a plain lookup — otherwise `:constructor:`
        // and `:__proto__:` resolve to inherited Object members and get
        // stringified into the user's note.
        if (!hasOwn.call(SHORTCODES, key)) return match;
        previousEnd = offset + match.length;
        return SHORTCODES[key];
      });
    },

    /**
     * Same, but a no-op when the user has emoji rendering turned off.
     * This is the entry point render paths should use.
     */
    render(text) {
      if (!this.isEnabled()) return text;
      return this.replaceShortcodes(text);
    },

    /**
     * Substitute shortcodes inside an already-rendered HTML string,
     * walking text nodes so `:joy:` inside <code>/<pre> and inside
     * attribute values (href, src, …) is left alone. For render paths
     * that hand markdown to marked/DOMPurify rather than doing their
     * own inline pass.
     */
    renderInHtml(html) {
      if (!this.isEnabled()) return html;
      if (!html || html.indexOf(":") === -1) return html;
      const doc = new DOMParser().parseFromString(html, "text/html");
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          let p = node.parentNode;
          while (p && p !== doc.body) {
            const tag = p.tagName;
            if (tag === "CODE" || tag === "PRE") {
              return NodeFilter.FILTER_REJECT;
            }
            p = p.parentNode;
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      });
      const targets = [];
      let node;
      while ((node = walker.nextNode())) targets.push(node);
      targets.forEach((textNode) => {
        const replaced = this.replaceShortcodes(textNode.nodeValue);
        if (replaced !== textNode.nodeValue) textNode.nodeValue = replaced;
      });
      return doc.body.innerHTML;
    },
  };

  window.brainspreadEmoji = brainspreadEmoji;

  // Vue options mixin for components that render content through a
  // method rather than a computed. A method has no dependency list of
  // its own, so nothing would re-run it when a rendering setting flips;
  // reading `emojiRenderKey` inside the method registers the dependency
  // against whichever render effect is active, and bumping the key on a
  // settings event re-renders those consumers without a page reload.
  //
  // Despite the name, this now also covers the hashtag/property
  // highlighting toggles (see content-highlighting.js) — same shape of
  // problem (a display-only user setting a markdown-rendering method
  // needs to react to), so it reuses the same key and mixin rather than
  // adding a near-identical one per setting.
  //
  // Loaded before the components in base.html, so it's there by the time
  // a component's options object is built.
  window.brainspreadEmojiRenderMixin = {
    data() {
      return { emojiRenderKey: 0 };
    },

    mounted() {
      this._onRenderSettingChanged = () => {
        // Block content is unchanged — only its rendering is — so a
        // reactive bump is enough; no refetch needed.
        this.emojiRenderKey += 1;
      };
      document.addEventListener(
        "brainspread:emoji-setting-changed",
        this._onRenderSettingChanged
      );
      document.addEventListener(
        "brainspread:highlight-setting-changed",
        this._onRenderSettingChanged
      );
    },

    beforeUnmount() {
      document.removeEventListener(
        "brainspread:emoji-setting-changed",
        this._onRenderSettingChanged
      );
      document.removeEventListener(
        "brainspread:highlight-setting-changed",
        this._onRenderSettingChanged
      );
    },
  };
})();
