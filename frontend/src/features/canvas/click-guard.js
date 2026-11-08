// A drag that ends over the same element still fires `click`. Selection (which opens the inspector) must only happen on a real click.
export const CLICK_MOVE_TOLERANCE = 5;

export const pressPoint = (event) => ({ x: event.clientX, y: event.clientY });

// `press` is the point recorded on pointerdown; with no recorded press (keyboard activation) the click is accepted.
export const isClick = (press, event, tolerance = CLICK_MOVE_TOLERANCE) => !press || Math.hypot(event.clientX - press.x, event.clientY - press.y) <= tolerance;
