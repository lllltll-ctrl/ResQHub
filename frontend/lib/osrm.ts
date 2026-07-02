// Дорожній маршрут через публічний OSRM.
//
// Демо-сервер OSRM підтримує лише профіль "driving", тож для пішоходів
// беремо дорожню ВІДСТАНЬ (маршрут по вулицях, з урахуванням перешкод) і
// рахуємо час за швидкістю ходьби. Це набагато точніше за «пряму лінію»,
// яка ігнорує будівлі/річки й тому давала занижений час.

export interface RoadRoute {
  distanceM: number;
  coords: [number, number][]; // [lat, lon] для полілінії на карті
}

const OSRM_BASE = "https://router.project-osrm.org/route/v1/driving";

// Кеш у пам'яті: один і той самий маршрут не запитуємо двічі.
const cache = new Map<string, RoadRoute | null>();

export async function fetchRoadRoute(
  fromLat: number,
  fromLon: number,
  toLat: number,
  toLon: number,
): Promise<RoadRoute | null> {
  const key = `${fromLat.toFixed(4)},${fromLon.toFixed(4)}->${toLat.toFixed(4)},${toLon.toFixed(4)}`;
  const cached = cache.get(key);
  if (cached !== undefined) return cached;

  try {
    const url = `${OSRM_BASE}/${fromLon},${fromLat};${toLon},${toLat}?overview=full&geometries=geojson`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`OSRM ${res.status}`);
    const data = await res.json();
    const route = data?.routes?.[0];
    if (!route) throw new Error("OSRM: no route");
    const coords: [number, number][] = (route.geometry?.coordinates ?? []).map(
      (c: [number, number]) => [c[1], c[0]],
    );
    const result: RoadRoute = { distanceM: Math.round(route.distance), coords };
    cache.set(key, result);
    return result;
  } catch {
    // Фолбек — нехай викликач використає пряму відстань.
    cache.set(key, null);
    return null;
  }
}

// Пішохідний час (хв) із дорожньої відстані. ~5 км/год = 83 м/хв.
export function walkMinutes(distanceM: number): number {
  return Math.max(1, Math.round(distanceM / 83));
}
