// Hashtag / key::value property chip highlighting toggles.
//
// All three settings only affect how Page.formatContentWithTags renders
// content — the underlying #hashtag and key::value text in a block is
// unchanged either way, and the link still navigates when the chip
// styling is off. Mirrors emoji.js's isEnabled() read pattern: cached
// against the raw localStorage string so a login/logout/settings-save
// (which all rewrite `user`) invalidates it for free.
(function () {
  const contentHighlighting = {
    _rawUser: undefined,
    _hashtagsEnabled: true,
    _propertyKeysEnabled: true,
    _propertyValuesEnabled: true,

    _refresh() {
      let raw = null;
      try {
        raw = window.localStorage ? localStorage.getItem("user") : null;
      } catch (_) {
        // localStorage throws in some private-browsing modes.
        raw = null;
      }
      if (raw === this._rawUser) return;
      this._rawUser = raw;
      let user = null;
      try {
        user = raw ? JSON.parse(raw) : null;
      } catch (_) {
        user = null;
      }
      // Default on — a user who has never touched the setting and the
      // logged-out case both get highlighting.
      this._hashtagsEnabled = user ? user.highlight_hashtags !== false : true;
      this._propertyKeysEnabled = user
        ? user.highlight_property_keys !== false
        : true;
      this._propertyValuesEnabled = user
        ? user.highlight_property_values !== false
        : true;
    },

    hashtagsEnabled() {
      this._refresh();
      return this._hashtagsEnabled;
    },

    propertyKeysEnabled() {
      this._refresh();
      return this._propertyKeysEnabled;
    },

    propertyValuesEnabled() {
      this._refresh();
      return this._propertyValuesEnabled;
    },
  };

  window.brainspreadContentHighlighting = contentHighlighting;
})();
