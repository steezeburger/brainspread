// Help Modal Component
window.HelpModal = {
  props: {
    isOpen: {
      type: Boolean,
      default: false,
    },
  },

  emits: ["close"],

  template: `
    <div v-if="isOpen" class="settings-modal" @click.self="$emit('close')">
      <div class="settings-modal-content help-modal-content">
        <div class="help-modal-header">
          <h2>help</h2>
          <button @click="$emit('close')" class="help-close-btn" title="Close">×</button>
        </div>

        <div class="help-modal-body">
          <div class="help-section">
            <h3>text formatting</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><code class="help-syntax">**bold**</code> or <code class="help-syntax">__bold__</code></td>
                  <td><strong>bold</strong></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">*italic*</code> or <code class="help-syntax">_italic_</code></td>
                  <td><em>italic</em></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">***bold italic***</code></td>
                  <td><strong><em>bold italic</em></strong></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">~~strikethrough~~</code></td>
                  <td><s>strikethrough</s></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">\`code\`</code></td>
                  <td><code class="markdown-code">code</code></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">==highlight==</code></td>
                  <td><span class="markdown-highlight">highlight</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">&gt; blockquote</code></td>
                  <td><span class="markdown-quote">blockquote</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">#tagname</code></td>
                  <td><span class="inline-tag">#tagname</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">\\*</code></td>
                  <td>escape a special character</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="help-section">
            <h3>keyboard shortcuts</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><kbd>Enter</kbd></td>
                  <td>new block</td>
                </tr>
                <tr>
                  <td><kbd>Tab</kbd></td>
                  <td>indent block</td>
                </tr>
                <tr>
                  <td><kbd>Shift</kbd> + <kbd>Tab</kbd></td>
                  <td>outdent block</td>
                </tr>
                <tr>
                  <td><kbd>Backspace</kbd> on empty block</td>
                  <td>delete block</td>
                </tr>
                <tr>
                  <td><kbd>↑</kbd> / <kbd>↓</kbd></td>
                  <td>navigate between blocks</td>
                </tr>
                <tr>
                  <td>double <kbd>space</kbd> at start</td>
                  <td>indent block (mobile)</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="help-section">
            <h3>block actions</h3>
            <p class="help-hint">right-click any block bullet to access block actions: indent, outdent, move up/down, create before/after, add to AI context, and delete.</p>
          </div>
        </div>
      </div>
    </div>
  `,
};
