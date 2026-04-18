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
    "postgresql://postgres:OdYjBmILhUImSJkvvGOxnIzdfhtMTMnS@nozomi.proxy.rlwy.net:58081/railway"
)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. MODELOS RELACIONALES (3 TABLAS)
class Categoria(Base):
    __tablename__ = "categorias"
    id_categoria = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False, unique=True)
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
    
    categoria = relationship("Categoria", back_populates="productos")
    # Relación con la nueva tabla Stock
    inventario = relationship("Stock", back_populates="producto", uselist=False, cascade="all, delete-orphan")

class Stock(Base):
    __tablename__ = "stock"
    id_stock = Column(Integer, primary_key=True, index=True)
    cantidad = Column(Integer, default=0, nullable=False)
    id_producto = Column(Integer, ForeignKey("productos.id_producto", ondelete="CASCADE"), unique=True, nullable=False)
    producto = relationship("Producto", back_populates="inventario")

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
    cantidad_inicial: int 
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
    fecha_actualizacion: datetime
    cantidad_stock: int = 0 

    @classmethod
    def from_orm(cls, obj):
        return cls(
            id_producto=obj.id_producto, nombre=obj.nombre, descripcion=obj.descripcion,
            precio=obj.precio, url_imagen=obj.url_imagen, id_categoria=obj.id_categoria,
            activo=obj.activo, fecha_creacion=obj.fecha_creacion, 
            fecha_actualizacion=obj.fecha_actualizacion,
            cantidad_stock=obj.inventario.cantidad if obj.inventario else 0
        )

class StockUpdate(BaseModel):
    cantidad_a_restar: int

class StockResponse(BaseModel):
    id_stock: int
    cantidad: int
    id_producto: int
    class Config: from_attributes = True

# 4. INICIALIZACIÓN
app = FastAPI(title="WS 2 - Gestión Completa con Tabla Stock")
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ... (Se mantienen los imports y la configuración de DB igual al inicio)

# 5. ENDPOINTS DE CATEGORÍAS (CRUD COMPLETO)
@app.get("/categorias", response_model=List[CategoriaResponse])
def get_categorias(db: Session = Depends(get_db)):
    return db.query(Categoria).order_by(Categoria.id_categoria.asc()).all()

@app.post("/categorias", response_model=CategoriaResponse)
def create_categoria(categoria: CategoriaCreate, db: Session = Depends(get_db)):
    nueva = Categoria(nombre=categoria.nombre)
    db.add(nueva); db.commit(); db.refresh(nueva)
    return nueva

@app.put("/categorias/{id_categoria}", response_model=CategoriaResponse)
def update_categoria(id_categoria: int, cat_data: CategoriaCreate, db: Session = Depends(get_db)):
    cat = db.query(Categoria).filter(Categoria.id_categoria == id_categoria).first()
    if not cat: raise HTTPException(status_code=404, detail="Categoría no encontrada")
    cat.nombre = cat_data.nombre
    db.commit(); db.refresh(cat)
    return cat

@app.delete("/categorias/{id_categoria}")
def delete_categoria(id_categoria: int, db: Session = Depends(get_db)):
    cat = db.query(Categoria).filter(Categoria.id_categoria == id_categoria).first()
    if not cat: raise HTTPException(status_code=404, detail="Categoría no encontrada")
    try:
        db.delete(cat); db.commit()
        return {"mensaje": "Categoría eliminada"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="No se puede eliminar: hay productos usándola")

# 6. ENDPOINTS DE PRODUCTOS (CRUD COMPLETO + LÓGICA DE STOCK)
@app.get("/productos", response_model=List[ProductoResponse])
def get_productos(db: Session = Depends(get_db)):
    productos = db.query(Producto).all()
    return [ProductoResponse.from_orm(p) for p in productos]

@app.post("/productos", response_model=ProductoResponse)
def create_producto(producto: ProductoCreate, db: Session = Depends(get_db)):
    # 1. Crear el producto
    nuevo_p = Producto(
        nombre=producto.nombre, 
        descripcion=producto.descripcion, 
        precio=producto.precio,
        url_imagen=producto.url_imagen, 
        id_categoria=producto.id_categoria, 
        activo=producto.activo 
    )
    db.add(nuevo_p)
    db.flush() # Esto genera el ID del producto sin cerrar la transacción

    # 2. Crear AUTOMÁTICAMENTE el registro en la tabla stock
    nuevo_s = Stock(id_producto=nuevo_p.id_producto, cantidad=producto.cantidad_inicial)
    db.add(nuevo_s)
    
    db.commit()
    db.refresh(nuevo_p)
    return ProductoResponse.from_orm(nuevo_p)
@app.put("/productos/{id_producto}", response_model=ProductoResponse)
def update_producto(id_producto: int, p_data: ProductoCreate, db: Session = Depends(get_db)):
    p = db.query(Producto).filter(Producto.id_producto == id_producto).first()
    if not p: raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    p.nombre = p_data.nombre
    p.descripcion = p_data.descripcion
    p.precio = p_data.precio
    p.id_categoria = p_data.id_categoria
    p.url_imagen = p_data.url_imagen
    p.activo = p_data.activo
    
    # También actualizamos la cantidad en la tabla stock si viene en el PUT
    if p.inventario:
        p.inventario.cantidad = p_data.cantidad_inicial
        
    db.commit(); db.refresh(p)
    return ProductoResponse.from_orm(p)

@app.delete("/productos/{id_producto}")
def delete_producto(id_producto: int, db: Session = Depends(get_db)):
    p = db.query(Producto).filter(Producto.id_producto == id_producto).first()
    if not p: raise HTTPException(status_code=404, detail="Producto no encontrado")
    db.delete(p); db.commit() # Al borrar producto, se borra su stock por el 'cascade'
    return {"mensaje": "Producto y su stock eliminados correctamente"}

# 7. ENDPOINTS DE CONSULTA Y ACTUALIZACIÓN DE STOCK
@app.get("/stock", response_model=List[StockResponse])
def get_all_stock(db: Session = Depends(get_db)):
    return db.query(Stock).all()

@app.patch("/productos/{id_producto}/update-stock")
def update_stock(id_producto: int, payload: StockUpdate, db: Session = Depends(get_db)):
    item = db.query(Stock).filter(Stock.id_producto == id_producto).first()
    if not item: raise HTTPException(status_code=404, detail="Stock no encontrado")
    if item.cantidad < payload.cantidad_a_restar:
        raise HTTPException(status_code=400, detail="Stock insuficiente")
    item.cantidad -= payload.cantidad_a_restar
    if item.cantidad == 0: item.producto.activo = False
    db.commit()
    return {"mensaje": "Stock actualizado", "nuevo_stock": item.cantidad}

# ... (Se mantienen upload-imagen y reporte-bajo-stock igual)
# 8. IMÁGENES Y REPORTES (MANTENIENDO TU LÓGICA ORIGINAL)
@app.post("/upload-imagen")
async def upload_imagen(file: UploadFile = File(...)):
    file_location = f"uploads/{file.filename}"
    with open(file_location, "wb+") as f: shutil.copyfileobj(file.file, f)
    url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000").rstrip("/")
        return {"url": f"{url}/uploads/{file.filename}"}

@app.get("/productos/reporte/bajo-stock", response_model=List[ProductoResponse])
def reporte_bajo_stock(umbral: int = 10, db: Session = Depends(get_db)):
    prods = db.query(Producto).join(Stock).filter(Stock.cantidad <= umbral).all()
    return [ProductoResponse.from_orm(p) for p in prods]

