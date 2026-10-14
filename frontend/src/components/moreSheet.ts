// The phone tab bar's "More" sheet: the pages that do not earn a tab of their
// own. Escape and the backdrop both close it, so it can never trap the user.

export function moreSheet() {
  return {
    open: false,
    toggle() {
      this.open = !this.open;
    },
    close() {
      this.open = false;
    },
  };
}
