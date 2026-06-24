# Módulo de Contabilidad — Guía completa de integración
**SIS POS · Sistema multisucursal**
> Documento para el agente full-stack especializado en contabilidad.
> Cubre backend implementado, estructura de respuestas y arquitectura del dashboard.

---

## 1. Contexto del sistema

### Multi-tenant
- El sistema maneja **Empresas** → **Tiendas** → **Empleados**.
- Cada request está scoped automáticamente a la empresa del usuario autenticado.
- El superadmin puede ver todas las empresas pasando `?empresa=<id>`.

### Roles (campo `rol` en el usuario)
| Rol | Acceso contabilidad |
|---|---|
| `superadmin` | Todo, todas las empresas |
| `admin` | Todo de su empresa |
| `supervisor` | Todo de su empresa |
| `cajero` | Solo gastos visibles (`visibilidad=todos`) y reporte diario |

### Base URL
```
/api/contabilidad/
```

### Autenticación
Todos los endpoints requieren header:
```
Authorization: Bearer <access_token>
```
Los tokens se obtienen desde `/api/auth/token/` (POST con `username` + `password`).

---

## 2. Modelos de datos relevantes

### Gasto
```
tienda          ForeignKey(Tienda)
empleado        ForeignKey(Empleado, null)
sesion_caja     ForeignKey(SesionCaja, null)
categoria       CharField(max_length=80)      — texto libre
descripcion     TextField
monto           DecimalField(12,2)
metodo_pago     "efectivo" | "tarjeta" | "transferencia"
visibilidad     "todos" | "solo_admin"        — cajeros solo ven "todos"
tipo_gasto      "fijo" | "variable"           — para punto de equilibrio
created_at      DateTimeField
```

**Categorías que auto-asignan `visibilidad=solo_admin`:**
`arriendo`, `nomina`, `servicios`, `mercancia`, `recibo`, `proveedor`, `impuesto`, `administrativo`

**Diferencia fijo vs variable:**
- **Fijo**: arriendo, nómina, servicios públicos — no cambian con el volumen
- **Variable**: comisiones, empaques, suministros — proporcionales a las ventas
- El frontend debe mostrar un selector al crear/editar gastos

### DetalleVenta (costo de ventas)
```
venta           ForeignKey(Venta)
producto        ForeignKey(Producto)
cantidad        DecimalField(10,2)
precio_unitario DecimalField(12,2)            — precio de venta al cliente
costo_unitario  DecimalField(12,2, null)      — precio_compra al momento de la venta
descuento       DecimalField(12,2)
subtotal        DecimalField(12,2)
```
> `costo_unitario` se llena automáticamente desde `producto.precio_compra` al crear la venta.
> Para datos históricos (antes de la implementación) se usa `producto.precio_compra` actual como fallback.

### SesionCaja
```
tienda               ForeignKey(Tienda)
empleado             ForeignKey(Empleado, null)
fecha_apertura       DateTimeField
fecha_cierre         DateTimeField(null)
monto_inicial        DecimalField(12,2)
monto_final_sistema  DecimalField(12,2, null)   — calculado al cierre
monto_final_real     DecimalField(12,2, null)   — ingresado por el cajero
diferencia           DecimalField(12,2, null)   — real - sistema
estado               "abierta" | "cerrada"
```

---

## 3. Endpoints CRUD de Gastos

### `GET /api/contabilidad/gastos/`
Lista gastos. Roles: todos.

**Query params:**
| Param | Tipo | Default | Notas |
|---|---|---|---|
| `fecha` | ISO date | hoy | Un día exacto |
| `fecha_ini` | ISO date | — | Inicio de rango (usar con fecha_fin) |
| `fecha_fin` | ISO date | — | Fin de rango |
| `tienda_id` | int | — | Filtrar por tienda |
| `categoria` | string | — | Filtro por categoría (case-insensitive) |
| `visibilidad` | `todos`\|`solo_admin` | — | Solo admin/supervisor |

> El cajero solo ve gastos de **su tienda**, **hoy**, con `visibilidad=todos`.

**Respuesta (array):**
```json
[
  {
    "id": 12,
    "tienda": 3,
    "tienda_nombre": "Sucursal Norte",
    "sesion_caja": 7,
    "empleado": 4,
    "empleado_nombre": "Ana García",
    "categoria": "arriendo",
    "descripcion": "Alquiler local mes junio",
    "monto": "850000.00",
    "metodo_pago": "transferencia",
    "visibilidad": "solo_admin",
    "tipo_gasto": "fijo",
    "created_at": "2026-06-15T10:30:00Z"
  }
]
```

### `POST /api/contabilidad/gastos/`
Crea un gasto. Roles: todos (autenticado).

**Body:**
```json
{
  "tienda": 3,
  "categoria": "arriendo",
  "descripcion": "Alquiler junio",
  "monto": "850000.00",
  "metodo_pago": "transferencia",
  "visibilidad": "solo_admin",
  "tipo_gasto": "fijo"
}
```
> `empleado` y `sesion_caja` se asignan automáticamente en el backend.
> Si `visibilidad` no se envía, el backend la infiere según `categoria` y `rol`.

### `GET /api/contabilidad/gastos/<id>/`
Detalle de un gasto. Roles: admin/supervisor.

### `DELETE /api/contabilidad/gastos/<id>/`
Elimina un gasto. Roles: admin/supervisor.

---

## 4. Resumen de gastos por rango

### `GET /api/contabilidad/gastos/resumen-rango/`
Roles: admin/supervisor.

**Query params:** `fecha_ini` (requerido), `fecha_fin` (requerido), `tienda_id`, `categoria`

**Respuesta:**
```json
{
  "fecha_ini": "2026-06-01",
  "fecha_fin": "2026-06-30",
  "total": 2450000.00,
  "cantidad": 8,
  "por_categoria": [
    { "categoria": "arriendo", "total": 850000.00, "cantidad": 1 },
    { "categoria": "nomina",   "total": 1200000.00, "cantidad": 1 }
  ],
  "por_dia": [
    { "dia": "2026-06-01", "total": 850000.00, "cantidad": 1 }
  ]
}
```

---

## 5. Reportes temporales

### `GET /api/contabilidad/reportes/diario/`
Roles: todos.

**Query params:** `fecha` (ISO, default hoy), `tienda_id`
> El cajero siempre ve solo su tienda.

**Respuesta:**
```json
{
  "fecha": "2026-06-22",
  "total_ventas": 1500000.00,
  "num_ventas": 34,
  "total_gastos": 120000.00,
  "total_devoluciones": 45000.00,
  "num_devoluciones": 2,
  "total_neto": 1455000.00,
  "utilidad_bruta": 1335000.00,
  "ventas_por_metodo_pago": [
    { "metodo": "efectivo", "total": 900000.00, "cantidad": 20 },
    { "metodo": "tarjeta",  "total": 600000.00, "cantidad": 14 }
  ],
  "devoluciones_por_metodo": [
    { "metodo": "efectivo", "total": 45000.00, "cantidad": 2 }
  ],
  "gastos_por_categoria": [
    { "categoria": "servicios", "total": 80000.00, "cantidad": 1 }
  ]
}
```
> `gastos_por_categoria` solo se retorna a admin/supervisor, no a cajero.

---

### `GET /api/contabilidad/reportes/mensual/`
Roles: admin/supervisor.

**Query params:** `anio` (default año actual), `mes` (1-12, default mes actual), `tienda_id`

**Respuesta:**
```json
{
  "anio": 2026,
  "mes": 6,
  "total_ventas": 45000000.00,
  "total_gastos": 5200000.00,
  "total_devoluciones": 800000.00,
  "total_neto": 44200000.00,
  "utilidad_bruta": 39000000.00,
  "ventas_por_dia": [
    { "dia": "2026-06-01", "total": 1500000.00, "cantidad": 34 }
  ],
  "gastos_por_categoria": [
    { "categoria": "arriendo", "total": 850000.00 }
  ],
  "gastos_por_dia": [
    { "dia": "2026-06-01", "total": 120000.00 }
  ],
  "devoluciones_por_dia": [
    { "dia": "2026-06-01", "total": 45000.00, "cantidad": 2 }
  ]
}
```

---

### `GET /api/contabilidad/reportes/anual/`
Roles: admin/supervisor.

**Query params:** `anio` (default año actual), `tienda_id`

**Respuesta:**
```json
{
  "anio": 2026,
  "total_ventas": 540000000.00,
  "total_gastos": 62400000.00,
  "total_devoluciones": 9600000.00,
  "total_neto": 530400000.00,
  "utilidad_bruta": 468000000.00,
  "meses": [
    {
      "mes": 1,
      "nombre": "Enero",
      "ventas": 45000000.00,
      "devoluciones": 800000.00,
      "neto": 44200000.00,
      "gastos": 5200000.00,
      "utilidad": 39000000.00,
      "cantidad": 980
    }
  ]
}
```
> `meses` siempre tiene 12 elementos (uno por mes, con ceros si no hay datos).

---

### `GET /api/contabilidad/reportes/top-productos/`
Roles: todos.

**Query params:** `fecha_ini`, `fecha_fin`, `tienda_id`
> Retorna top 10. El cajero siempre ve solo su tienda.

**Respuesta (array de 10):**
```json
[
  {
    "producto": "Arroz Diana 500g",
    "total_vendido": 320.0,
    "total_ingresos": 480000.00
  }
]
```

---

## 6. Estado de Resultados (P&L)

### `GET /api/contabilidad/reportes/estado-resultados/`
Roles: admin/supervisor.

**Query params:** `fecha_ini`, `fecha_fin`, `tienda_id`
> Por defecto: mes actual (día 1 hasta hoy).

**Respuesta:**
```json
{
  "periodo": {
    "desde": "2026-06-01",
    "hasta": "2026-06-22",
    "tienda_id": null
  },
  "ingresos": {
    "ventas_brutas": 45000000.00,
    "menos_descuentos": 900000.00,
    "menos_devoluciones": 800000.00,
    "ingresos_netos": 44200000.00,
    "impuestos_cobrados": 3200000.00,
    "num_ventas": 980,
    "num_devoluciones": 18
  },
  "costo_ventas": 24300000.00,
  "margen_bruto": 19900000.00,
  "margen_bruto_pct": 45.02,
  "gastos_operativos": {
    "total": 5200000.00,
    "detalle": [
      { "categoria": "nomina",   "total": 2400000.00, "cantidad": 2 },
      { "categoria": "arriendo", "total": 1700000.00, "cantidad": 2 },
      { "categoria": "servicios","total": 1100000.00, "cantidad": 4 }
    ]
  },
  "averias": {
    "perdidas_brutas": 350000.00,
    "valor_recuperado": 120000.00,
    "perdida_neta": 230000.00
  },
  "utilidad_operativa": 14470000.00,
  "utilidad_operativa_pct": 32.74
}
```

**Fórmulas aplicadas:**
```
ingresos_netos     = ventas_brutas - devoluciones
margen_bruto       = ingresos_netos - costo_ventas
utilidad_operativa = margen_bruto - total_gastos - perdida_neta_averias
margen_bruto_pct   = margen_bruto / ingresos_netos * 100
```

---

## 7. Comparativo entre tiendas

### `GET /api/contabilidad/reportes/comparativo-tiendas/`
Roles: admin/supervisor.

**Query params:** `fecha_ini`, `fecha_fin`
> No acepta `tienda_id`: siempre muestra **todas** las tiendas de la empresa.

**Respuesta:**
```json
{
  "periodo": { "desde": "2026-06-01", "hasta": "2026-06-22" },
  "tiendas": [
    {
      "tienda_id": 3,
      "tienda_nombre": "Sucursal Norte",
      "ventas_brutas": 28000000.00,
      "devoluciones": 400000.00,
      "ingresos_netos": 27600000.00,
      "costo_ventas": 15200000.00,
      "margen_bruto": 12400000.00,
      "margen_bruto_pct": 44.93,
      "gastos": 3100000.00,
      "perdida_averias": 150000.00,
      "utilidad_operativa": 9150000.00,
      "num_ventas": 620,
      "num_devoluciones": 10
    }
  ],
  "totales": {
    "ventas_brutas": 45000000.00,
    "devoluciones": 800000.00,
    "ingresos_netos": 44200000.00,
    "costo_ventas": 24300000.00,
    "margen_bruto": 19900000.00,
    "margen_bruto_pct": 45.02,
    "gastos": 5200000.00,
    "perdida_averias": 230000.00,
    "utilidad_operativa": 14470000.00,
    "num_ventas": 980
  }
}
```
> `tiendas` viene ordenado de mayor a menor `utilidad_operativa`.

---

## 8. Ventas por empleado

### `GET /api/contabilidad/reportes/ventas-por-empleado/`
Roles: admin/supervisor.

**Query params:** `fecha_ini`, `fecha_fin`, `tienda_id`

**Respuesta:**
```json
{
  "periodo": { "desde": "2026-06-01", "hasta": "2026-06-22", "tienda_id": null },
  "empleados": [
    {
      "empleado_id": 4,
      "nombre": "Ana García",
      "num_ventas": 220,
      "total_ventas": 18500000.00,
      "total_descuentos": 370000.00,
      "promedio_venta": 84090.91
    }
  ]
}
```
> Ordenado de mayor a menor `total_ventas`.

---

## 9. Punto de Equilibrio

### `GET /api/contabilidad/reportes/punto-equilibrio/`
Roles: admin/supervisor.

**Query params:** `fecha_ini`, `fecha_fin`, `tienda_id`

**Respuesta:**
```json
{
  "periodo": { "desde": "2026-06-01", "hasta": "2026-06-22", "tienda_id": null },
  "ingresos_netos": 44200000.00,
  "costo_ventas": 24300000.00,
  "gastos_fijos": 4100000.00,
  "gastos_variables": 1100000.00,
  "margen_contribucion": 18800000.00,
  "margen_contribucion_pct": 42.53,
  "punto_equilibrio_ingresos": 9641200.00,
  "punto_equilibrio_alcanzado": true,
  "excedente_deficit": 34558800.00,
  "detalle_gastos_fijos": [
    { "categoria": "nomina",   "total": 2400000.00 },
    { "categoria": "arriendo", "total": 1700000.00 }
  ],
  "detalle_gastos_variables": [
    { "categoria": "servicios", "total": 1100000.00 }
  ]
}
```

**Fórmulas:**
```
margen_contribucion     = ingresos_netos - costo_ventas - gastos_variables
margen_contribucion_pct = margen_contribucion / ingresos_netos * 100
punto_equilibrio        = gastos_fijos / (margen_contribucion_pct / 100)
excedente_deficit       = ingresos_netos - punto_equilibrio  (+: ganancia, -: pérdida)
```

> Si `punto_equilibrio_ingresos` es `null`, los costos superan los ingresos y no es calculable.

---

## 10. Flujo de Caja

### `GET /api/contabilidad/reportes/flujo-caja/`
Roles: admin/supervisor.

**Query params:** `fecha_ini`, `fecha_fin`, `tienda_id`

**Respuesta:**
```json
{
  "periodo": { "desde": "2026-06-01", "hasta": "2026-06-22", "tienda_id": null },
  "resumen": {
    "total_entradas": 45000000.00,
    "total_salidas": 5200000.00,
    "flujo_neto": 39800000.00,
    "total_diferencias": -85000.00,
    "num_sesiones": 44
  },
  "sesiones": [
    {
      "sesion_id": 12,
      "fecha": "2026-06-01",
      "tienda_id": 3,
      "tienda_nombre": "Sucursal Norte",
      "empleado": "Ana García",
      "monto_inicial": 200000.00,
      "entradas": {
        "ventas_efectivo": 900000.00,
        "ventas_tarjeta": 600000.00,
        "ventas_transferencia": 150000.00,
        "ventas_mixto": 0.00,
        "abonos": 50000.00,
        "total": 1700000.00
      },
      "salidas": {
        "gastos": 120000.00,
        "devoluciones": 45000.00,
        "total": 165000.00
      },
      "flujo_sesion": 1535000.00,
      "monto_final_sistema": 1735000.00,
      "monto_final_real": 1720000.00,
      "diferencia": -15000.00,
      "estado": "cerrada"
    }
  ]
}
```

---

## 11. Exportación a Excel

### `GET /api/contabilidad/reportes/exportar/`
Roles: admin/supervisor.

**Query params:**
| Param | Valores | Descripción |
|---|---|---|
| `tipo` | `estado-resultados` \| `flujo-caja` | Tipo de reporte a exportar |
| `fecha_ini` | ISO date | Inicio del período |
| `fecha_fin` | ISO date | Fin del período |
| `tienda_id` | int | Opcional |

**Respuesta:** archivo `.xlsx` con `Content-Disposition: attachment`.

**Implementación Flutter:**
```dart
// Descarga y guarda el archivo
final response = await dio.get(
  '/api/contabilidad/reportes/exportar/',
  queryParameters: {
    'tipo': 'estado-resultados',
    'fecha_ini': '2026-06-01',
    'fecha_fin': '2026-06-22',
  },
  options: Options(responseType: ResponseType.bytes),
);
// Guardar con path_provider + open_file
```

---

## 12. Arquitectura del Dashboard de Contabilidad

### Pantalla principal — Admin/Supervisor

```
┌─────────────────────────────────────────────────────────┐
│  FILTROS GLOBALES: [Período ▼]  [Tienda ▼]             │
├──────────────┬──────────────┬──────────────┬────────────┤
│ Ingresos     │ Costo ventas │ Margen bruto │ Utilidad   │
│ netos        │ (COGS)       │ + %          │ operativa  │
│ /estado-res..│ /estado-res..│ /estado-res..│ /estado-r..│
├──────────────┴──────────────┴──────────────┴────────────┤
│  GRÁFICA: Ventas vs Gastos vs Utilidad por día (/mensual)│
├─────────────────────────┬───────────────────────────────┤
│ Comparativo tiendas     │ Top empleados                 │
│ /comparativo-tiendas/   │ /ventas-por-empleado/         │
│ Tabla con columnas:     │ Ranking con barras            │
│ Tienda | Ventas | Margen│ Nombre | Ventas | Promedio    │
│ | Gastos | Utilidad     │                               │
├─────────────────────────┴───────────────────────────────┤
│ PUNTO DE EQUILIBRIO (/punto-equilibrio/)                │
│  Gauge: [====|====] PE alcanzado: SÍ                    │
│  Excedente: $34.558.800 | MC%: 42.53%                   │
├─────────────────────────────────────────────────────────┤
│ FLUJO DE CAJA (/flujo-caja/)                            │
│  Gráfica barras: Entradas vs Salidas por sesión/día     │
│  Tabla: Fecha | Cajero | Entradas | Salidas | Diferencia│
└─────────────────────────────────────────────────────────┘
                              [⬇ Exportar Excel ▼]
```

### Pantalla secundaria — Gastos
```
┌─────────────────────────────────────────────────────────┐
│ [+ Nuevo gasto]   Filtros: Fecha | Categoría | Tipo     │
├──────────────┬──────────────────────────────────────────┤
│ Total gastos │ Fijos: $X  |  Variables: $X              │
│ mes actual   │ /gastos/resumen-rango/                   │
├──────────────┴──────────────────────────────────────────┤
│ Donut: Gastos por categoría                             │
├─────────────────────────────────────────────────────────┤
│ Tabla de gastos                                         │
│ Fecha | Categoría | Tipo | Monto | Método | Empleado   │
│ [Editar] [Eliminar]  — solo admin/supervisor            │
└─────────────────────────────────────────────────────────┘
```

### Pantalla de cierre de día — Cajero
```
┌─────────────────────────────────────────────────────────┐
│ RESUMEN DEL DÍA  /reportes/diario/                      │
├──────────────┬──────────────┬────────────────────────── ┤
│ Ventas hoy   │ Devoluciones │ Total neto                │
├──────────────┴──────────────┴───────────────────────────┤
│ Por método de pago (efectivo | tarjeta | transferencia) │
├─────────────────────────────────────────────────────────┤
│ Mis gastos del día /gastos/?fecha=hoy                   │
│ [+ Registrar gasto]                                     │
└─────────────────────────────────────────────────────────┘
```

---

## 13. Guía de navegación de períodos (UX)

El frontend debe ofrecer selectores de período que mapeen a los parámetros de cada endpoint:

| Selector UI | Endpoint a usar | Params enviados |
|---|---|---|
| "Hoy" | `/reportes/diario/` | `fecha=YYYY-MM-DD` |
| "Esta semana" | `/reportes/estado-resultados/` | `fecha_ini=lunes&fecha_fin=hoy` |
| "Este mes" | `/reportes/mensual/` ó `/reportes/estado-resultados/` | `mes=N&anio=YYYY` ó rango |
| "Este año" | `/reportes/anual/` | `anio=YYYY` |
| "Rango custom" | Todos los de rango | `fecha_ini=X&fecha_fin=Y` |

---

## 14. Notas técnicas para el agente

### Cálculo de `utilidad_bruta` vs `utilidad_operativa`
Los endpoints históricos (`/diario/`, `/mensual/`, `/anual/`) retornan `utilidad_bruta = ventas - devoluciones - gastos`. **Este valor NO descuenta COGS.** Es una aproximación rápida.

El endpoint `/reportes/estado-resultados/` es el **P&L real** con COGS incluido. Usar este para contabilidad formal.

### Tipo de cambio COGS en datos históricos
`costo_unitario` en `DetalleVenta` es `null` para ventas anteriores a la implementación. En esos casos el sistema usa `producto.precio_compra` **actual** como fallback. Esto puede no reflejar el costo histórico real si los precios cambiaron.

### El campo `tipo_gasto` para punto de equilibrio
- Default: `"fijo"` para todos los gastos existentes.
- El frontend **debe** mostrar un selector `Fijo / Variable` al crear un gasto.
- Sin este dato bien cargado, el punto de equilibrio no será preciso.

### Scope automático multi-tienda
Todos los endpoints filtran automáticamente por empresa del usuario. El admin ve **todas sus tiendas** por defecto. Para filtrar una sola tienda, pasar `?tienda_id=N`.

### Exportación — manejo en Flutter
```dart
// El endpoint devuelve bytes, no JSON
final bytes = response.data as List<int>;
final dir = await getApplicationDocumentsDirectory();
final file = File('${dir.path}/reporte.xlsx');
await file.writeAsBytes(bytes);
await OpenFile.open(file.path);
```

### Permisos en Flutter — qué mostrar a cada rol
```dart
switch (user.rol) {
  case 'cajero':
    // Mostrar solo: resumen diario + registro de gastos
    break;
  case 'supervisor':
  case 'admin':
  case 'superadmin':
    // Mostrar dashboard completo
    break;
}
```

---

## 15. Resumen de todos los endpoints

| Endpoint | Método | Roles | Notas |
|---|---|---|---|
| `gastos/` | GET | Todos | Filtros por fecha/tienda/categoría |
| `gastos/` | POST | Todos | Crea gasto |
| `gastos/<id>/` | GET/DELETE | Admin/Sup | Detalle y borrado |
| `gastos/resumen-rango/` | GET | Admin/Sup | Requiere fecha_ini + fecha_fin |
| `reportes/diario/` | GET | Todos | Por día |
| `reportes/mensual/` | GET | Admin/Sup | Por mes |
| `reportes/anual/` | GET | Admin/Sup | Por año, incluye 12 meses |
| `reportes/top-productos/` | GET | Todos | Top 10 productos |
| `reportes/estado-resultados/` | GET | Admin/Sup | P&L con COGS real |
| `reportes/comparativo-tiendas/` | GET | Admin/Sup | Todas las tiendas en paralelo |
| `reportes/ventas-por-empleado/` | GET | Admin/Sup | Ranking de cajeros |
| `reportes/punto-equilibrio/` | GET | Admin/Sup | Break-even analysis |
| `reportes/flujo-caja/` | GET | Admin/Sup | Por sesión de caja |
| `reportes/exportar/?tipo=estado-resultados` | GET | Admin/Sup | Descarga Excel P&L |
| `reportes/exportar/?tipo=flujo-caja` | GET | Admin/Sup | Descarga Excel flujo |
