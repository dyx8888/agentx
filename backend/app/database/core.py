"""
Database Core - SQLAlchemy Session Management
Provides database session management and engine configuration
"""

import os  # 閫氳繃鐜鍙橀噺娉ㄥ叆鏁版嵁搴撹繛鎺ヤ俊鎭紝閬垮厤纭紪鐮侊紝鏀寔涓嶅悓閮ㄧ讲鐜鐏垫椿鍒囨崲

import re
from pathlib import Path

from sqlalchemy import (
    create_engine,  # SQLAlchemy 鏍稿績宸ュ巶鍑芥暟锛岀粺涓€涓嶅悓鏁版嵁搴撳悗绔殑鍒涘缓鍏ュ彛
    inspect,
    text,
)
from sqlalchemy.orm import (  # Session 鐢ㄤ簬绫诲瀷鏍囨敞浠ユ彁鍗?IDE 鏅鸿兘鎻愮ず锛泂essionmaker 鏄細璇濆伐鍘傛ā寮?
    Session,
    sessionmaker,
)
from sqlalchemy.pool import (
    QueuePool,  # SQLite 涔熺敤 QueuePool锛歞ef 璺敱璧?threadpool 鏃讹紝姣忎釜绾跨▼鐨?Session 闇€鐙崰杩炴帴锛孲taticPool 鍗曡繛鎺ヤ細瀵艰嚧 Session 绾跨▼瀹夊叏闂
)

from app.core.logging import get_logger  # 缁撴瀯鍖栨棩蹇楋紝鏂逛究鍦ㄥ垎甯冨紡鐜涓寜妯″潡杩借釜鏁版嵁搴撳垵濮嬪寲鐘舵€?

from .models import Base  # 鎵€鏈?ORM 妯″瀷鍏变韩鍚屼竴涓?declarative_base锛屽缓琛ㄦ椂鍙渶閬嶅巻涓€娆?metadata

logger = get_logger(__name__)  # 妯″潡绾?logger锛屾寜 __name__ 鑷姩鐢熸垚灞傜骇鍛藉悕绌洪棿锛屼究浜庢棩蹇楄繃婊?

# 妯″潡绾у崟渚嬪彉閲忥紝閲囩敤鎳掑垵濮嬪寲妯″紡锛?
# 涓嶅湪 import 鏃剁洿鎺ュ垵濮嬪寲 engine锛岃€屾槸绛夊埌 FastAPI 鍚姩浜嬩欢涓皟鐢?init_database()锛?
# 杩欐牱鍙互纭繚鐜鍙橀噺宸茶鍔犺浇銆佹棩蹇楃郴缁熷凡灏辩华
_engine = None
_SessionLocal = None


def init_database():
    """Initialize database engine based on configuration"""
    global _engine, _SessionLocal  # 蹇呴』澹版槑 global锛屽惁鍒?Python 浼氬湪鍑芥暟鍐呴儴鍒涘缓鍚屽悕灞€閮ㄥ彉閲忚€岄潪淇敼妯″潡绾у崟渚?

    database_url = os.getenv(
        "DATABASE_URL"
    )  # 浠庣幆澧冨彉閲忚鍙栵紝Docker/docker-compose 涓敞鍏ワ紝鏈湴寮€鍙戝彲鍦?.env 涓厤缃?
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or "dev").strip().lower()

    if env in {"prod", "production"} and not (
        database_url and database_url.startswith("postgresql")
    ):
        raise RuntimeError(
            "DATABASE_URL must point to PostgreSQL when ENV=prod; "
            "SQLite fallback is only allowed for local development/tests."
        )

    if database_url and database_url.startswith("postgresql"):
        # 鐢熶骇鐜璧?PostgreSQL鈥斺€旀垚鐔熺殑鍏崇郴鍨嬫暟鎹簱锛屾敮鎸佽繛鎺ユ睜銆佸苟鍙戣鍐欍€佽绾ч攣
        logger.info("database_postgres_initializing")
        _engine = create_engine(
            database_url,
            pool_pre_ping=True,  # 姣忔浠庤繛鎺ユ睜鍙栧嚭杩炴帴鏃跺厛鍙戜竴鏉?SELECT 1 鎺㈡祴瀛樻椿锛岄槻姝娇鐢ㄥ凡琚暟鎹簱鏈嶅姟绔叧闂殑鍍靛案杩炴帴
            pool_recycle=300,  # 姣?300 绉掑己鍒跺洖鏀惰繛鎺ワ紝闃叉鏁版嵁搴撶锛堝 PgBouncer/RDS锛夊厛浜庡鎴风鏂紑绌洪棽杩炴帴瀵艰嚧鎶ラ敊
            pool_size=20,  # 杩炴帴姹犲父椹昏繛鎺ユ暟锛氶粯璁?5 鍦ㄥ async 璺敱鍚屾闃诲 + 鍗曡姹傚 session 鍦烘櫙涓嬫瀬鏄撹€楀敖
            max_overflow=20,  # 绐佸彂娴侀噺鏃跺厑璁歌秴鍑?pool_size 鐨勯澶栬繛鎺ワ紝鎬讳笂闄?40锛屽钩琛″嘲鍊间笌鏁版嵁搴撳帇鍔?
            pool_timeout=30,  # 绛夊緟杩炴帴姹犲彲鐢ㄨ繛鎺ョ殑鏈€闀挎椂闂?绉?锛岃秴鏃舵姏 TimeoutError 閬垮厤鏃犻檺鍫嗙Н
            echo=False,  # 鐢熶骇鐜绂佹鎵撳嵃 SQL锛岄伩鍏嶆硠闇叉晱鎰熸暟鎹拰鎾戠垎鏃ュ織鏂囦欢
        )
    else:
        # SQLite 浣滀负鍏滃簳鏂规锛氶浂閰嶇疆銆佹棤闇€鐙珛鏁版嵁搴撹繘绋嬶紝閫傚悎鏈湴寮€鍙戝拰鍗曟満娴嬭瘯
        logger.info("database_sqlite_initializing")
        db_filename = (
            "test_agentx.db" if os.getenv("TEST_MODE") == "true" else "agentx.db"
        )  # 娴嬭瘯妯″紡浣跨敤鐙珛鏁版嵁搴撴枃浠讹紝闃叉姹℃煋寮€鍙戞暟鎹?
        db_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(__file__))
            ),  # 鍚戜笂涓夊眰锛歝ore.py -> database -> app -> backend
            "data",  # 缁熶竴鏀惧湪 data/ 鐩綍涓嬶紝鏂逛究 .gitignore 蹇界暐鍜?Docker volume 鎸傝浇
            db_filename,
        )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # SQLite 浣跨敤 QueuePool锛堝杩炴帴姹狅級锛歞ef 璺敱琚?FastAPI 鏀惧叆 threadpool 鎵ц鏃讹紝
        # 姣忎釜绾跨▼鐨?Session 浼氫粠姹犱腑鑾峰彇鐙珛杩炴帴锛岄伩鍏?StaticPool 鍗曡繛鎺ュ叡浜鑷寸殑
        # Session 绾跨▼瀹夊叏闂锛堢棁鐘讹細Could not refresh instance锛夈€?
        # SQLite 鏂囦欢绾у啓閿?+ timeout 涓茶鍖栧啓鍏ワ紱璇绘搷浣滀娇鐢?WAL 妯″紡鍙苟琛屻€?
        _engine = create_engine(
            f"sqlite:///{db_path}",
            poolclass=QueuePool,
            pool_size=10,  # 甯搁┗杩炴帴鏁帮細涓?FastAPI 榛樿 threadpool (40 绾跨▼) 鍗忚皟锛?0 涓繛鎺ヨ冻浠ュ簲瀵瑰父瑙佸苟鍙?
            max_overflow=10,  # 绐佸彂娴侀噺鏃跺厑璁告墿瀹瑰埌 20 杩炴帴锛屽钩琛?SQLite 鏂囦欢閿佺珵浜変笌骞跺彂鑳藉姏
            pool_timeout=30,  # 绛夊緟杩炴帴瓒呮椂 30s锛岄伩鍏嶈姹傛棤闄愬爢绉?
            pool_pre_ping=True,  # 鍙栧嚭杩炴帴鍓嶆帰娴嬪瓨娲伙紝闃叉浣跨敤宸插け鏁堢殑杩炴帴
            connect_args={
                "check_same_thread": False,  # FastAPI 璇锋眰绾跨▼涓?engine 鍒涘缓绾跨▼涓嶅悓锛屽繀椤诲叧闂?SQLite 榛樿鐨勭嚎绋嬫鏌?
                "timeout": 30,  # 鍐欓攣绛夊緟 30s锛屾瘮榛樿 5s 鏇村瀹癸紝鍑忓皯楂樺苟鍙戝啓鏃剁殑 "database is locked"
            },
            echo=False,
        )
        # 鍚敤 WAL 妯″紡锛氳鍐欏垎绂伙紙璇讳笉闃诲鍐欍€佸啓涓嶉樆濉炶锛夛紝鏄捐憲鎻愬崌 SQLite 骞跺彂璇绘€ц兘
        # PRAGMA 鍦ㄦ瘡涓柊杩炴帴寤虹珛鏃舵墽琛岋紝纭繚鎵€鏈夎繛鎺ラ兘鐢?WAL
        from sqlalchemy import event

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")  # NORMAL 鍦?WAL 涓嬭冻澶熷畨鍏ㄤ笖鏇村揩锛孎ULL 澶參
            cursor.execute(
                "PRAGMA busy_timeout=30000"
            )  # ms 绾?busy timeout锛屼笌 connect_args.timeout 浜掕ˉ
            cursor.close()

    # 浼氳瘽宸ュ巶閰嶇疆锛歛utocommit=False 瑕佹眰鏄惧紡鎻愪氦浜嬪姟锛岄槻姝㈡剰澶栧啓鍏ワ紱
    # autoflush=False 閬垮厤鏌ヨ鍓嶈嚜鍔?flush 鑴忔暟鎹鑷撮殣寮?DB 鎿嶄綔锛屾彁鍗囨€ц兘骞惰琛屼负鍙娴?
    # expire_on_commit=False锛歝ommit 鍚庝笉鑷姩浣垮璞″睘鎬ц繃鏈燂紝閬垮厤鍦?session 鍏抽棴鍚庤闂睘鎬?
    # 瑙﹀彂 DetachedInstanceError锛堟湰椤圭洰澶ч噺鏂规硶鍦?with 鍧楀唴 commit 鍚庤繑鍥?ORM 瀵硅薄锛?
    _SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=_engine, expire_on_commit=False
    )

    # create_all 鏄箓绛夋搷浣溾€斺€斿凡瀛樺湪鐨勮〃涓嶄細閲嶅鍒涘缓锛屽洜姝ゅ彲浠ュ畨鍏ㄥ湴鍦ㄦ瘡娆″惎鍔ㄦ椂璋冪敤锛?
    # 杩欐牱鏂板妯″瀷鍚庢棤闇€鎵嬪姩鎵ц DDL 鑴氭湰
    logger.info("database_creating_tables")
    Base.metadata.create_all(bind=_engine)
    _ensure_runtime_schema_compatibility(_engine)
    _ensure_alembic_version_baseline(_engine)
    logger.info("database_tables_created")


def _ensure_runtime_schema_compatibility(engine) -> None:
    """琛ラ綈鍘嗗彶鏈湴搴撶己澶辩殑杞婚噺 schema銆?

    create_all 鍙細鍒涘缓涓嶅瓨鍦ㄧ殑琛紝涓嶄細缁欏凡鏈夎〃琛ユ柊鍒椼€傛湰椤圭洰鏈湴 SQLite
    缁忓父璺ㄧ増鏈鐢紝鍥犳鍦ㄥ惎鍔ㄩ樁娈佃ˉ榻愬凡鐭ュ吋瀹瑰瓧娈碉紝閬垮厤闈為樆鏂?warning/error
    娣规病鐪熷疄鐢熶骇闂銆傛寮忕幆澧冧粛搴斾互 Alembic migration 涓哄噯銆?
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "users" in table_names:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "bio" not in user_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN bio TEXT"))
            logger.info("database_schema_compat_column_added", table="users", column="bio")
        if "token_version" not in user_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
            logger.info(
                "database_schema_compat_column_added", table="users", column="token_version"
            )

    if "evolution_log" in table_names:
        evolution_columns = {column["name"] for column in inspector.get_columns("evolution_log")}
        if "training_data_path" not in evolution_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE evolution_log ADD COLUMN training_data_path TEXT"))
            logger.info(
                "database_schema_compat_column_added",
                table="evolution_log",
                column="training_data_path",
            )

    # llm_usage 宸茬撼鍏?ORM metadata锛涜繖閲屼繚鐣?checkfirst 鍏滃簳锛岃鐩栨棫搴?閮ㄥ垎娴嬭瘯搴撱€?    Base.metadata.tables["llm_usage"].create(bind=engine, checkfirst=True)


def _detect_alembic_head_revision() -> str | None:
    """Return the single Alembic head revision from local migration files."""
    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    revisions: dict[str, str | None] = {}

    for path in versions_dir.glob("*.py"):
        text_value = path.read_text(encoding="utf-8-sig")
        revision_match = re.search(r'^revision:\s*str\s*=\s*["\']([^"\']+)["\']', text_value, re.M)
        if not revision_match:
            continue
        down_match = re.search(
            r'^down_revision:\s*str\s*\|\s*None\s*=\s*(?:["\']([^"\']+)["\']|None)',
            text_value,
            re.M,
        )
        revisions[revision_match.group(1)] = down_match.group(1) if down_match else None

    referenced = {down for down in revisions.values() if down}
    heads = sorted(set(revisions) - referenced)
    if len(heads) != 1:
        logger.warning("alembic_head_detection_failed", heads=heads)
        return None
    return heads[0]


def _stamp_alembic_version_baseline(engine, revision: str) -> bool:
    """Create/populate alembic_version when the DB was initialized by create_all."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "alembic_version" not in table_names:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            logger.info("alembic_version_table_created")

        row_count = conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() or 0
        if row_count > 0:
            return False

        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )
        logger.info("alembic_version_baseline_stamped", revision=revision)
        return True


def _ensure_alembic_version_baseline(engine) -> None:
    """Ensure PostgreSQL cold-start databases have a traceable Alembic baseline."""
    if getattr(engine.dialect, "name", "") != "postgresql":
        return

    head_revision = _detect_alembic_head_revision()
    if not head_revision:
        return

    _stamp_alembic_version_baseline(engine, head_revision)


def get_session() -> Session:
    """
    Get database session dependency for FastAPI
    Returns a new session that should be closed after use
    """
    if _SessionLocal is None:
        raise RuntimeError(
            "Database not initialized. Call init_database() first."
        )  # 蹇€熷け璐ユ瘮 NoneType AttributeError 鏇存槗鎺掓煡

    return _SessionLocal()  # 姣忔璋冪敤閮藉垱寤烘柊浼氳瘽锛屾弧瓒?FastAPI 渚濊禆娉ㄥ叆鐨?姣忚姹備竴浼氳瘽"妯″紡锛岄伩鍏嶄細璇濊法璇锋眰鍏变韩瀵艰嚧鏁版嵁姹℃煋


def get_engine():
    """Get the database engine"""
    if _engine is None:
        raise RuntimeError(
            "Database not initialized. Call init_database() first."
        )  # 闃插尽鎬ф鏌ワ紝Alembic 杩佺Щ鍜屽師鐢?SQL 鎿嶄綔渚濊禆 engine 瀹炰緥

    return _engine


def close_database():
    """Close database connections"""
    global _engine, _SessionLocal  # 闇€瑕佸皢妯″潡绾у彉閲忕疆鍥?None 浠ユ敮鎸侀噸鏂板垵濮嬪寲锛堜緥濡傛祴璇曠幆澧?tearDown锛?

    if _engine:
        _engine.dispose()  # 閲婃斁杩炴帴姹犱腑鎵€鏈夎繛鎺ワ紝浼橀泤鍏抽棴鏃堕伩鍏嶈繛鎺ユ硠婕忓拰鏈嶅姟绔畫鐣欒繛鎺?
        logger.info("database_connections_closed")


# FastAPI 渚濊禆娉ㄥ叆寮忕殑鏁版嵁搴撲細璇濊幏鍙栧嚱鏁帮細
# 鍒╃敤鐢熸垚鍣ㄧ殑 yield 璇硶锛孎astAPI 浼氬湪璇锋眰杩涘叆鏃惰幏鍙栦細璇濄€佽姹傜粨鏉熸椂鑷姩鎵ц finally 鍧楀叧闂細璇濓紝
# 杩欐牱璺敱鍑芥暟鏃犻渶鎵嬪姩绠＄悊浼氳瘽鐢熷懡鍛ㄦ湡锛屽噺灏戦仐婕忓叧闂鑷寸殑杩炴帴娉勬紡椋庨櫓
def get_db():
    """
    FastAPI dependency for database session
    Automatically handles session lifecycle
    """
    db = get_session()
    try:
        yield db  # yield 灏嗘帶鍒舵潈浜ょ粰 FastAPI锛岃妗嗘灦鍦ㄨ矾鐢卞嚱鏁颁腑浣跨敤璇ヤ細璇?
    finally:
        db.close()  # 鏃犺璇锋眰鎴愬姛杩樻槸鎶涘紓甯革紝閮戒細鎵ц姝ゅ鍏抽棴鎿嶄綔锛屼繚璇佽繛鎺ュ綊杩樻睜涓?
