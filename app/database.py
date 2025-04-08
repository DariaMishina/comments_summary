from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
import datetime

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()

class RequestLog(Base):
    __tablename__ = "request_logs"
    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String, index=True)
    status = Column(String)
    task_id = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

def log_request(endpoint: str, status: str, task_id: str = None):
    session = SessionLocal()
    log = RequestLog(endpoint=endpoint, status=status, task_id=task_id)
    session.add(log)
    session.commit()
    session.close()

def update_task_status(task_id: str, status: str):
    session = SessionLocal()
    log = session.query(RequestLog).filter_by(task_id=task_id).first()
    if log:
        log.status = status
        session.commit()
    session.close()

def get_task_status(task_id: str):
    """
    Получает статус задачи по task_id из базы данных.
    """
    session = SessionLocal()
    log = session.query(RequestLog).filter_by(task_id=task_id).first()
    session.close()
    
    if log:
        return log.status
    return None  
