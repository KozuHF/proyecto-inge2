from apps.actividades.models import Actividad

EMOJI_POR_DEPORTE = {
    Actividad.Nombre.FUTBOL: "⚽",
    Actividad.Nombre.BASKET: "🏀",
    Actividad.Nombre.PADDLE: "🎾",
    Actividad.Nombre.VOLEY: "🏐",
}

COLOR_RING_POR_DEPORTE = {
    Actividad.Nombre.FUTBOL: "bg-green-100 group-hover:bg-green-200",
    Actividad.Nombre.BASKET: "bg-orange-100 group-hover:bg-orange-200",
    Actividad.Nombre.PADDLE: "bg-blue-100 group-hover:bg-blue-200",
    Actividad.Nombre.VOLEY: "bg-yellow-100 group-hover:bg-yellow-200",
}

HORAS_ANTELACION_CREDITO = 48
DIAS_VALIDEZ_CREDITO = 30
