from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os

# 1. CONFIGURACIÓN DE LA BASE DE DATOS
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
    # Relación con productos
    productos = relationship("Producto", back_populates="categoria")

class Producto(Base):
    __tablename__ = "productos"
    id_producto = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(255), nullable=False)
    descripcion = Column(Text, nullable=True)
    precio = Column(Numeric(10, 2), nullable=False)
    url_imagen = Column(String(500), nullable=True)
    fecha_creacion = Column(DateTime, server_default=func.now(), nullable=False)
    fecha_actualizacion = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    id_categoria = Column(Integer, ForeignKey("categorias.id_categoria", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)

    # Relaciones
    categoria = relationship("Categoria", back_populates="productos")
    inventario = relationship("Stock", back_populates="producto", uselist=False, cascade="all, delete-orphan")

class Stock(Base):
    __tablename__ = "stock"
    id_stock = Column(Integer, primary_key=True, index=True)
    cantidad = Column(Integer, default=0, nullable=False)
    id_producto = Column(Integer, ForeignKey("productos.id_producto", ondelete="CASCADE"), unique=True, nullable=False)
    
    # Relación con Producto
    producto = relationship("Producto", back_populates="inventario")

# Crear tablas
Base.metadata.create_all(bind=engine)

# 3. ESQUEMAS PYDANTIC
class CategoriaCreate(BaseModel):
    nombre: str

class CategoriaResponse(CategoriaCreate):
    id_categoria: int
    class Config: from_attributes = True

class ProductoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    precio: float
    cantidad_inicial: int  # Para crear el stock inicial
    url_imagen: Optional[str] = None
    id_categoria: int
    activo: bool = True 

class ProductoResponse(BaseModel):
    id_producto: int
    nombre: str
    descripcion: Optional[str]
    precio: float
    url_imagen: Optional[str]
    id_categoria: int
    activo: bool
    fecha_creacion: datetime
    # Atajo para mostrar la cantidad del stock en la respuesta del producto
    cantidad_stock: int = 0 

    @classmethod
    def from_orm(cls, obj):
        # Lógica para extraer la cantidad de la tabla relacionada Stock
        cantidad = obj.inventario.cantidad if obj.inventario else 0
        return cls(
            id_producto=obj.id_producto, nombre=obj.nombre, descripcion=obj.descripcion,
            precio=obj.precio, url_imagen=obj.url_imagen, id_categoria=obj.id_categoria,
            activo=obj.activo, fecha_creacion=obj.fecha_creacion, cantidad_stock=cantidad
        )

class StockUpdate(BaseModel):
    cantidad_a_restar: int

# 4. INICIALIZACIÓN
app = FastAPI(title="WS 2 - Gestión de Productos e Inventario (Con Tabla Stock)")
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

FRONTEND_URL = os.getenv("FRONTEND_URL", "*") 
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_URL] if FRONTEND_URL != "*" else ["*"], 
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# 5. ENDPOINTS DE CATEGORÍAS (Igual que antes)
@app.get("/categorias", response_model=List[CategoriaResponse])
def get_categorias(db: Session = Depends(get_db)):
    return db.query(Categoria).order_by(Categoria.id_categoria.asc()).all()

@app.post("/categorias", response_model=CategoriaResponse)
def create_categoria(categoria: CategoriaCreate, db: Session = Depends(get_db)):
    cat_existe = db.query(Categoria).filter(Categoria.nombre == categoria.nombre).first()
    if cat_existe: raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre")
    nueva_categoria = Categoria(nombre=categoria.nombre)
    db.add(nueva_categoria)
    db.commit(); db.refresh(nueva_categoria)
    return nueva_categoria

# 6. ENDPOINTS DE PRODUCTOS (Adaptados a tabla Stock)
@app.get("/productos", response_model=List[ProductoResponse])
def get_productos(db: Session = Depends(get_db)):
    productos = db.query(Producto).all()
    return [ProductoResponse.from_orm(p) for p in productos]

@app.post("/productos", response_model=ProductoResponse)
def create_producto(producto: ProductoCreate, db: Session = Depends(get_db)):
    categoria_existe = db.query(Categoria).filter(Categoria.id_categoria == producto.id_categoria).first()
    if not categoria_existe: raise HTTPException(status_code=404, detail="La categoría no existe")
    
    # 1. Crear el producto
    nuevo_p = Producto(
        nombre=producto.nombre, descripcion=producto.descripcion, precio=producto.precio,
        url_imagen=producto.url_imagen, id_categoria=producto.id_categoria, activo=producto.activo 
    )
    db.add(nuevo_p)
    db.flush() # Para obtener el ID del producto antes del commit final

    # 2. Crear el registro en la tabla Stock
    nuevo_stock = Stock(id_producto=nuevo_p.id_producto, cantidad=producto.cantidad_inicial)
    db.add(nuevo_stock)
    
    db.commit()
    db.refresh(nuevo_p)
    return ProductoResponse.from_orm(nuevo_p)

@app.patch("/productos/{id_producto}/update-stock")
def update_stock(id_producto: int, payload: StockUpdate, db: Session = Depends(get_db)):
    # Buscamos el stock directamente por el ID del producto
    stock_item = db.query(Stock).filter(Stock.id_producto == id_producto).first()
    if not stock_item: raise HTTPException(status_code=404, detail="Inventario no encontrado")
    
    if stock_item.cantidad < payload.cantidad_a_restar:
        raise HTTPException(status_code=400, detail=f"Stock insuficiente. Solo quedan {stock_item.cantidad} unidades.")
    
    stock_item.cantidad -= payload.cantidad_a_restar
    
    if stock_item.cantidad == 0:
        stock_item.producto.activo = False
        
    db.commit()
    return {"mensaje": "Stock actualizado", "nuevo_stock": stock_item.cantidad}

@app.get("/productos/reporte/bajo-stock", response_model=List[ProductoResponse])
def reporte_bajo_stock(umbral: int = 10, db: Session = Depends(get_db)):
    # Join con la tabla stock para filtrar por cantidad
    productos = db.query(Producto).join(Stock).filter(Stock.cantidad <= umbral, Producto.activo == True).all()
    return [ProductoResponse.from_orm(p) for p in productos]

@app.post("/upload-imagen")
async def upload_imagen(file: UploadFile = File(...)):
    file_location = f"uploads/{file.filename}"
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000").rstrip("/")
    return {"url": f"{base_url}/uploads/{file.filename}"}