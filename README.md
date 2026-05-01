# Setup del Proyecto (Django + .venv + Tailwind + Flowbite)

## 1. Crear y activar entorno virtual (.venv)

### Crear entorno:

```bash
python -m venv .venv
```

### Activar:

**Linux / macOS**

```bash
source .venv/bin/activate
```

**Windows (PowerShell)**

```bash
.venv\Scripts\Activate.ps1
```

---

## 2. Instalar dependencias de Python

```bash
pip install -r requirements.txt
```

---

## 3. Instalar Tailwind CSS

Instalar Tailwind como dependencia de desarrollo:

```bash
npm install tailwindcss @tailwindcss/cli --save-dev
```

Ejecutar Tailwind en modo watch (compila automáticamente los estilos):

```bash
npx @tailwindcss/cli -i ./static/src/input.css -o ./static/src/output.css --watch
```

---

## 4. Instalar Flowbite

Flowbite agrega componentes interactivos (modales, navbars, dropdowns, etc).

Instalar con NPM:

```bash
npm install flowbite --save
```

---

## 5. Notas importantes

* Asegurate de tener **Node.js y npm instalados**
* El entorno `.venv` debe estar activado para trabajar con Django
* Ejecutar Tailwind en paralelo mientras desarrollás
* No subir `.venv` ni `node_modules` al repositorio (ya están en `.gitignore`)

---

## 6. Flujo típico de trabajo

1. Activar `.venv`
2. Levantar Django:

   ```bash
   python manage.py runserver
   ```
3. Ejecutar Tailwind:

   ```bash
   npx @tailwindcss/cli -i ./static/src/input.css -o ./static/src/output.css --watch
   ```

---