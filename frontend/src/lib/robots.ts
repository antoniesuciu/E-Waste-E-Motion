// Robot inventory shared by every view. IDs come from the backend (src/config.py ROBOT_IDS),
// injected by templates/index.html, so the UI never offers a robot the server rejects.
declare global {
  interface Window { ROBOT_IDS?: number[] }
}

export const ROBOT_IDS: number[] = window.ROBOT_IDS ?? [];

const NICKNAMES: Record<number, string> = {
  1: 'AMIS',
  2: 'OGLINDA',
  3: 'FOTOLIU',
  4: 'SCANNER',
  5: 'ASPIRATOR',
  6: 'JUCARIE 1',
  7: 'JUCARIE 2',
  8: 'BRAT',
  9: 'BROSELE',
  10: 'LUMINI',
};

export const robotLabel = (id: number): string => NICKNAMES[id] ?? `Robot ${id}`;

export const NONE_LABEL = 'Fără robot';
