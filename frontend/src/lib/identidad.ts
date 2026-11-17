// Identidad del navegador frente a la API: dispositivo y licencia.
//
// Sin estas cabeceras la API identificaba a cada visitante solo por su IP, de
// modo que toda una oficina o universidad detras de un NAT compartia la misma
// cuota gratuita, y un suscriptor no se distinguia de un anonimo al analizar.
//
// La licencia es un portador (quien la tenga, la usa) y caduca sola. El
// identificador de dispositivo es aleatorio y no contiene ningun dato de la
// persona; la API ademas lo somete a hash antes de guardarlo.

export const CLAVE_LICENCIA = 'deepscan_licencia';
const CLAVE_DISPOSITIVO = 'deepscan_dispositivo';

// Eventos de la pagina. Un evento del navegador evita cablear estado global
// entre componentes que no comparten arbol (el menu y la zona de carga).
export const EVENTO_ABRIR_PLANES = 'deepscan:abrir-planes';
export const EVENTO_CONSUMO = 'deepscan:consumo';

function leer(clave: string): string | null {
  try { return localStorage.getItem(clave); } catch { return null; }
}

export function idDispositivo(): string {
  let id = leer(CLAVE_DISPOSITIVO);
  if (!id) {
    id = (typeof crypto !== 'undefined' && 'randomUUID' in crypto)
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    try { localStorage.setItem(CLAVE_DISPOSITIVO, id); } catch { /* modo privado */ }
  }
  return id;
}

export function licencia(): string | null {
  return leer(CLAVE_LICENCIA);
}

export function cabecerasIdentidad(): Record<string, string> {
  const h: Record<string, string> = { 'X-DeepScan-Device': idDispositivo() };
  const lic = licencia();
  if (lic) h['X-DeepScan-License'] = lic;
  return h;
}

export function abrirPlanes() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(EVENTO_ABRIR_PLANES));
}

export function avisarConsumo() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(EVENTO_CONSUMO));
}
