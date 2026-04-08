# backend2/main.py
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError # Para manejar errores de base de datos
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os

# 1. CONFIGURACIÓN DE LA BASE DE DATOS (POSTGRESQL)
# Usamos os.getenv para proteger las credenciales. Si no encuentra la variable (ej. en local), usará tu cadena por defecto.
# En Render, DEBES crear una variable de entorno llamada DATABASE_URL con tu cadena de conexión real.
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://admin:rnGDEbwD02DFHG6ozZrVcJtqTvpRlWTZ@dpg-d6t0tt15pdvs73e41uj0-a.oregon-postgres.render.com/inventariotienda_czox"
)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. MODELOS RELACIONALES
class Categoria(Base):
    __tablename__ = "categorias"
    id_categoria = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False, unique=True)

class Producto(Base):
    __tablename__ = "productos"
    id_producto = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    descripcion = Column(Text, nullable=True)
    precio = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer, nullable=False)
    url_imagen = Column(String(500), nullable=True)
    fecha_creacion = Column(DateTime, server_default=func.now(), nullable=False)
    fecha_actualizacion = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    id_categoria = Column(Integer, ForeignKey("categorias.id_categoria", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)

Base.metadata.create_all(bind=engine)

# 3. ESQUEMAS PYDANTIC
class CategoriaCreate(BaseModel):
    nombre: str

class CategoriaResponse(CategoriaCreate):
    id_categoria: int
    class Config:
        from_attributes = True

class ProductoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    precio: float
    stock: int
    url_imagen: Optional[str] = None
    id_categoria: int
    activo: bool = True 

class ProductoResponse(ProductoCreate):
    id_producto: int
    fecha_creacion: datetime
    fecha_actualizacion: datetime
    class Config:
        from_attributes = True

class StockUpdate(BaseModel):
    cantidad_a_restar: int

# 4. INICIALIZACIÓN
app = FastAPI(title="WS 2 - Gestión de Productos e Inventario")

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Configuramos el CORS de forma dinámica
# En Render, puedes crear una variable FRONTEND_URL con la URL de tu app en Vercel, Netlify o tu app móvil.
FRONTEND_URL = os.getenv("FRONTEND_URL", "*") 

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL] if FRONTEND_URL != "*" else ["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 5. ENDPOINTS DE CATEGORÍAS
@app.get("/categorias", response_model=List[CategoriaResponse])
def get_categorias(db: Session = Depends(get_db)):
    return db.query(Categoria).order_by(Categoria.id_categoria.asc()).all()

@app.post("/categorias", response_model=CategoriaResponse)
def create_categoria(categoria: CategoriaCreate, db: Session = Depends(get_db)):
    cat_existe = db.query(Categoria).filter(Categoria.nombre == categoria.nombre).first()
    if cat_existe: raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre")
    nueva_categoria = Categoria(nombre=categoria.nombre)
    db.add(nueva_categoria)
    db.commit()
    db.refresh(nueva_categoria)
    return nueva_categoria

@app.put("/categorias/{id_categoria}", response_model=CategoriaResponse)
def update_categoria(id_categoria: int, categoria: CategoriaCreate, db: Session = Depends(get_db)):
    cat = db.query(Categoria).filter(Categoria.id_categoria == id_categoria).first()
    if not cat: raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    cat.nombre = categoria.nombre
    try:
        db.commit()
        db.refresh(cat)
        return cat
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="El nombre ya está en uso por otra categoría.")

@app.delete("/categorias/{id_categoria}")
def delete_categoria(id_categoria: int, db: Session = Depends(get_db)):
    cat = db.query(Categoria).filter(Categoria.id_categoria == id_categoria).first()
    if not cat: raise HTTPException(status_code=404, detail="Categoría no encontrada")
    
    try:
        db.delete(cat)
        db.commit()
        return {"mensaje": "Categoría eliminada exitosamente"}
    except IntegrityError: 
        db.rollback()
        raise HTTPException(status_code=400, detail="No puedes eliminar esta categoría porque hay productos que la están usando. Reasigna o elimina los productos primero.")

# 6. ENDPOINTS DE PRODUCTOS E IMÁGENES
@app.get("/productos", response_model=List[ProductoResponse])
def get_productos(db: Session = Depends(get_db)):
    return db.query(Producto).order_by(Producto.id_producto.desc()).all()

@app.post("/productos", response_model=ProductoResponse)
def create_producto(producto: ProductoCreate, db: Session = Depends(get_db)):
    categoria_existe = db.query(Categoria).filter(Categoria.id_categoria == producto.id_categoria).first()
    if not categoria_existe: raise HTTPException(status_code=404, detail="La categoría no existe")
    
    nuevo_producto = Producto(
        nombre=producto.nombre, descripcion=producto.descripcion, precio=producto.precio,
        stock=producto.stock, url_imagen=producto.url_imagen, id_categoria=producto.id_categoria,
        activo=producto.activo 
    )
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    return nuevo_producto

@app.put("/productos/{id_producto}", response_model=ProductoResponse)
def update_producto(id_producto: int, p_act: ProductoCreate, db: Session = Depends(get_db)):
    producto = db.query(Producto).filter(Producto.id_producto == id_producto).first()
    if not producto: raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    producto.nombre = p_act.nombre
    producto.descripcion = p_act.descripcion
    producto.precio = p_act.precio
    producto.stock = p_act.stock
    if p_act.url_imagen: producto.url_imagen = p_act.url_imagen
    producto.id_categoria = p_act.id_categoria
    producto.activo = p_act.activo 
    
    db.commit()
    db.refresh(producto)
    return producto

@app.delete("/productos/{id_producto}")
def delete_producto(id_producto: int, db: Session = Depends(get_db)):
    producto = db.query(Producto).filter(Producto.id_producto == id_producto).first()
    if not producto: raise HTTPException(status_code=404, detail="Producto no encontrado")
    db.delete(producto)
    db.commit()
    return {"mensaje": "Producto eliminado exitosamente"}

@app.post("/upload-imagen")
async def upload_imagen(file: UploadFile = File(...)):
    file_location = f"uploads/{file.filename}"
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    
    # MODIFICADO: Render inyecta automáticamente 'RENDER_EXTERNAL_URL' con tu dominio público.
    # Si no existe (ej. en local), hacemos un fallback a localhost:8000.
    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
    
    # Nos aseguramos de quitar cualquier barra final para no romper la URL
    base_url = base_url.rstrip("/")
    
    return {"url": f"{base_url}/uploads/{file.filename}"}
# Agregar esto en backend2/main.py (en la sección de endpoints de productos)

@app.get("/productos/reporte/bajo-stock", response_model=List[ProductoResponse])
def reporte_bajo_stock(umbral: int = 10, db: Session = Depends(get_db)):
    """
    HU20: Consultar un reporte específico de productos con bajo stock.
    Retorna todos los productos cuyo stock sea menor o igual al umbral especificado.
    Por defecto, el umbral es 10.
    """
    # Filtramos productos activos cuyo stock sea menor o igual al umbral
    productos_bajo_stock = db.query(Producto).filter(
        Producto.stock <= umbral,
        Producto.activo == True
    ).order_by(Producto.stock.asc()).all()
    
    # Si quisieras exportarlo a Excel desde Python, usaríamos pandas, 
    # pero enviar un JSON limpio le permite a tu frontend (React/Angular) 
    # mostrarlo en una tabla bonita al consultor.
    return productos_bajo_stock

@app.patch("/productos/{id_producto}/update-stock")
def update_stock(id_producto: int, payload: StockUpdate, db: Session = Depends(get_db)):
    # 1. Buscamos el producto
    producto = db.query(Producto).filter(Producto.id_producto == id_producto).first()
    if not producto: 
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    # 2. HU15: Validamos si hay stock suficiente
    if producto.stock < payload.cantidad_a_restar:
        raise HTTPException(
            status_code=400, 
            detail=f"Stock insuficiente. Solo quedan {producto.stock} unidades de {producto.nombre}."
        )
    
    # 3. HU14: Descontamos el stock
    producto.stock -= payload.cantidad_a_restar
    
    # BONUS: Si llega a 0, se inactiva.
    if producto.stock == 0:
        producto.activo = False
        
    db.commit()
    db.refresh(producto)
    
    
    return {"mensaje": "Stock actualizado exitosamente", "nuevo_stock": producto.stock}