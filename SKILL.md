---
description: "Control a myCobot 280 robot arm to physically interact with laptop devices — press keyboard keys, type text, swipe/tap touchpad, gesture, and manipulate objects in the workspace using multi-camera vision. IMPORTANT: You MUST decompose complex requests into multiple sequential tool calls. If the user says 'swipe up and down', call touchpad_swipe('up') THEN touchpad_swipe('down') as two separate calls."
applyTo: "**"
tools:
  - keyboard_press_key
  - keyboard_type_text
  - touchpad_swipe
  - touchpad_tap
  - robot_home
  - robot_power_on
  - robot_send_coords
  - robot_send_angles
  - robot_get_status
  - robot_finger_touch
  - robot_set_led
  - robot_head_shake
  - robot_head_nod
  - robot_head_dance
  - robot_stop
  - realsense_capture
  - camera_capture
  - vlm_ask_question
  - agent_execute
  - record_action
---

# MyCobotAgent — Physical Device Interaction Skill

You have control of a **myCobot 280 Pi** robot arm that can physically interact with a laptop keyboard and touchpad.

## CRITICAL: Action Planning

**You are responsible for breaking down every user request into a sequence of atomic tool calls.** Each tool performs ONE action. Complex requests require MULTIPLE sequential calls.

### How to plan actions:

1. **Parse the request** — identify all distinct actions the user wants
2. **Order them logically** — determine the correct sequence
3. **Call each tool in order** — one at a time, waiting for each to complete
4. **Verify and report** — confirm what was done

### Action decomposition examples:

| User says | You call (in order) |
|-----------|-------------------|
| "swipe up and down" | `touchpad_swipe("up")` → `touchpad_swipe("down")` |
| "swipe down 3 times" | `touchpad_swipe("down")` → `touchpad_swipe("down")` → `touchpad_swipe("down")` |
| "type hello then scroll down" | `keyboard_type_text("hello")` → `touchpad_swipe("down")` |
| "press A, B, then C" | `keyboard_press_key("a")` → `keyboard_press_key("b")` → `keyboard_press_key("c")` |
| "type cat and then swipe up twice" | `keyboard_type_text("cat")` → `touchpad_swipe("up")` → `touchpad_swipe("up")` |
| "do a dance then type sad" | `robot_head_dance()` → `keyboard_type_text("sad")` |
| "scroll to the bottom of the page" | `touchpad_swipe("down")` → `touchpad_swipe("down")` → `touchpad_swipe("down")` → ... (repeat until done) |
| "click the center and then scroll down" | `touchpad_tap(0.5, 0.5)` → `touchpad_swipe("down")` |
| "go home, turn LED red, then type test" | `robot_home()` → `robot_set_led(255, 0, 0)` → `keyboard_type_text("test")` |
| "type A S D one at a time" | `keyboard_press_key("a")` → `keyboard_press_key("s")` → `keyboard_press_key("d")` |
| "swipe left and right on touchpad" | `touchpad_swipe("left")` → `touchpad_swipe("right")` |

### Planning rules:

- **"and"** in a request means **MULTIPLE actions** — call each tool separately
- **"then"** means **sequential** — call in that order
- **"X times" / "a few times"** means **repeat** the tool call N times
- **"back and forth"** means call the action, then its reverse
- **"scroll down the page"** may need multiple swipe("down") calls
- When in doubt, **do more rather than less** — it's better to swipe 3 times than once
- Always call `robot_home()` at the end of a multi-step sequence

## Available Tools

### Keyboard

| Tool | Description | Args |
|------|-------------|------|
| `keyboard_type_text(text, speed)` | Type a string of characters | text: string, speed: "slow"/"medium"/"fast" |
| `keyboard_press_key(key)` | Press a single key | key: "a"-"z", "0"-"6", "esc", "tab" |

**Reachable keys** (left half only):
```
` 1 2 3 4 5 6
q w e r t y
a s d f g h
z x c v b
```
Keys on the right side (7-0, u-p, j-;, n-/) are NOT reachable.

### Touchpad

| Tool | Description | Args |
|------|-------------|------|
| `touchpad_swipe(direction)` | Swipe/scroll gesture | direction: "down", "up", "left", "right" |
| `touchpad_tap(x_frac, y_frac)` | Tap/click at position | x: 0.0-1.0 (left-right), y: 0.0-1.0 (top-bottom) |

### Robot Motion

| Tool | Description |
|------|-------------|
| `robot_home()` | Return arm to home position |
| `robot_send_coords(coords, speed)` | Move to [x,y,z,rx,ry,rz] |
| `robot_finger_touch(x, y)` | Touch a workspace point |
| `robot_stop()` | Emergency stop |

### Gestures & LED

| Tool | Description |
|------|-------------|
| `robot_head_shake()` | Shake head (no) |
| `robot_head_nod()` | Nod head (yes) |
| `robot_head_dance()` | Dance animation |
| `robot_set_led(r, g, b)` | Set LED color (0-255 each) |

### Vision

| Tool | Description |
|------|-------------|
| `realsense_capture()` | Capture overhead RGBD image |
| `camera_capture()` | Capture side-view image |
| `vlm_ask_question(question)` | Ask about workspace contents |

### Recording

| Tool | Description |
|------|-------------|
| `record_action(action, args)` | Execute an action while recording from all cameras, returns a GIF image in the chat |

The `record_action` tool is special — it **records video from all cameras while the robot performs an action**, then returns the GIF directly in the conversation. Use it when the user wants to **see** what the robot did.

**Actions supported by record_action:**
- `"type <text>"` — type text (e.g. `record_action("type sad")`)
- `"press <key>"` — press a key (e.g. `record_action("press a")`)
- `"swipe <direction>"` — touchpad swipe (e.g. `record_action("swipe down")`)
- `"tap"` — touchpad tap
- `"dance"` — dance animation
- `"shake"` / `"nod"` — gesture

**Examples:**
| User says | You call |
|-----------|----------|
| "type sad and show me" | `record_action("type sad")` |
| "record yourself swiping down" | `record_action("swipe down")` |
| "do a dance and film it" | `record_action("dance")` |
| "show me pressing the A key" | `record_action("press a")` |

Use `record_action` instead of the individual tools when the user wants visual proof or says things like "show me", "record", "film", "let me see", "demo".

## Complex Request Examples

### "Swipe the touchpad up and down for me"
```python
touchpad_swipe("up")     # First: swipe up
touchpad_swipe("down")   # Then: swipe down
```

### "Type 'test' then scroll down to see the result"
```python
keyboard_type_text("test", speed="fast")   # Type the text
touchpad_swipe("down")                      # Scroll to see result
touchpad_swipe("down")                      # Scroll more for good measure
```

### "Quickly swipe up 5 times"
```python
touchpad_swipe("up")
touchpad_swipe("up")
touchpad_swipe("up")
touchpad_swipe("up")
touchpad_swipe("up")
```

### "Show me you can type and use the touchpad — do a demo"
```python
keyboard_type_text("hello", speed="fast")   # Type something
touchpad_swipe("down")                       # Scroll down
touchpad_swipe("up")                         # Scroll back up
touchpad_tap(0.5, 0.5)                       # Click center
robot_head_nod()                             # Nod to confirm
robot_home()                                 # Return home
```

### "Navigate down the page and click on something"
```python
touchpad_swipe("down")      # Scroll down
touchpad_swipe("down")      # Scroll more
touchpad_tap(0.5, 0.5)      # Click center of touchpad
```

### "Press escape, then type 'quit', then press escape again"
```python
keyboard_press_key("esc")               # Press Esc
keyboard_type_text("quit", speed="fast") # Type quit
keyboard_press_key("esc")               # Press Esc again
```

## Important Notes

1. **ALWAYS decompose** — never ignore part of a request. "up and down" = 2 actions.
2. **Speed**: Default to "fast" unless user asks for slow/careful.
3. **Reachability**: Only left-half keys work. Inform user if characters can't be typed.
4. **Repeat**: "a few times" = 3, "several times" = 5, "many times" = 10.
5. **Return home**: Call `robot_home()` after multi-step sequences.
6. **Touchpad coords**: (0,0)=top-left, (1,1)=bottom-right, (0.5,0.5)=center.

## MCP Server Configuration

Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "mycobot": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "C:\\Users\\jiaqizou\\MyCobotAgent"
    }
  }
}
```
