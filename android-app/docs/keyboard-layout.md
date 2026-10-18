# Keyboard layout template

The on-screen keyboard is built from a layout you can edit in the app and as text.

## Editing in the app

Tap **layout** in the top bar. Then:

- **Tap** a key to select it (white outline). Nothing types while you edit.
- **Drag** a key to move it, within its row or into another row.
- **Drag a key's right edge** to resize it. The other keys in that row give or take the space, so the row always fills the width.
- Buttons for exact steps: `◀ move`, `move ▶`, `− width`, `+ width`, `− height`, `+ height` (height applies to the selected key's row).
- **next layer** cycles letters, fn, symbols1, symbols2 so you can edit each one.
- **copy** puts the whole layout on the clipboard as text. **paste** applies a layout from the clipboard (errors are listed with line numbers and nothing changes).
- **vibration** cycles off / light / medium / strong (each press vibrates on touch-down; the strength is saved).
- **reset** restores the default (tap it twice).
- Every change is saved automatically.

## The default layout

Letters: digits, qwerty, the indented home row, shift and backspace, a modifier row (esc, prtsc, win, ctrl, alt, fn), and a bottom row with 123, comma, space, full stop and enter. The arrow keys are on the 123 page (up arrow above down arrow), not on the letters page. fn shows F1 to F12 and Home / PgUp / PgDn / End. The 123 and =\\< pages follow Android's.

## The text format

```
remote-hid keyboard layout v1
layer letters
row 1.0  q|KeyQ  w|KeyW  @|Digit2|1|shift  space|Space|5  €|unicode|1||20ac
```

- `layer <name>` starts a layer; the first layer is the one shown by default.
- `row <height>` starts a row; the height is a multiple of the base row height (0.5 to 2.5). Keys follow on the same line, separated by spaces.
- A key is `label|code|width|mods|unicode`. Only `label|code` is required; width defaults to 1.
- In a label write `\|` for a pipe, `\\` for a backslash and `\s` for a space.
- `mods` is a comma list of `shift`, `ctrl`, `alt`, `meta`, pressed together with the key (`@` is `Digit2` with `shift`).
- `code` is one of:
  - a key name: `KeyA`..`KeyZ`, `Digit0`..`Digit9`, `F1`..`F12`, `Enter`, `Backspace`, `Space`, `Tab`, `Escape`, `ArrowUp/Down/Left/Right`, `Comma`, `Period`, `Minus`, `Equal`, `Semicolon`, `Quote`, `Slash`, `Backslash`, `BracketLeft`, `BracketRight`, `Backquote`, `PrintScreen`, `Home`, `End`, `PageUp`, `PageDown`, `Meta`
  - `shift`, `ctrl`, `alt`: sticky modifiers (tap to arm, applies to the next key)
  - `layer:<name>`: switch to that layer; tapping the toggle for the layer you are on goes back to the first layer
  - `spacer`: an invisible gap (the indent on the home row)
  - `unicode`: a character with no physical key; put its hex codepoint in the 5th field. Best effort: it relies on the desktop using IBus (Ctrl+Shift+U).

`docs/keyboard-layout.default.txt` is the default layout in this format: a good starting point to copy, change and paste back.

Keep the total height of each layer the same (the default layers each add up to 6.0) so the keyboard does not change size when you switch layers.
