import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Click the map to choose a point; `boxDeg` > 0 draws a box of that size around it.
export default function MapPicker({ lat, lon, boxDeg, onPick }) {
  const el = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    map.current = L.map(el.current).setView([lat, lon], 5);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 12,
    }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    map.current.on("click", (e) => pick.current(+e.latlng.lat.toFixed(4), +e.latlng.lng.toFixed(4)));
    return () => map.current.remove();
  }, []);

  useEffect(() => {
    layer.current.clearLayers();
    L.circleMarker([lat, lon], { radius: 7, color: "#b42318", fillOpacity: 0.9 }).addTo(layer.current);
    if (boxDeg > 0) {
      const h = boxDeg / 2;
      L.rectangle([[lat - h, lon - h], [lat + h, lon + h]], { color: "#b42318", weight: 1 }).addTo(layer.current);
    }
    map.current.panTo([lat, lon]);
  }, [lat, lon, boxDeg]);

  return <div ref={el} className="map" />;
}
