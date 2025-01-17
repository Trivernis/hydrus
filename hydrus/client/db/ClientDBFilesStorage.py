import collections
import sqlite3
import typing

from hydrus.core import HydrusConstants as HC
from hydrus.core import HydrusData
from hydrus.core import HydrusDB
from hydrus.core import HydrusDBModule

from hydrus.client.db import ClientDBMaster
from hydrus.client.db import ClientDBServices

def GenerateFilesTableNames( service_id: int ) -> typing.Tuple[ str, str, str, str ]:
    
    suffix = str( service_id )
    
    current_files_table_name = 'current_files_{}'.format( suffix )
    
    deleted_files_table_name = 'deleted_files_{}'.format( suffix )
    
    pending_files_table_name = 'pending_files_{}'.format( suffix )
    
    petitioned_files_table_name = 'petitioned_files_{}'.format( suffix )
    
    return ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name )
    
def GenerateFilesTableName( service_id: int, status: int ) -> str:
    
    ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
    
    if status == HC.CONTENT_STATUS_CURRENT:
        
        return current_files_table_name
        
    elif status == HC.CONTENT_STATUS_DELETED:
        
        return deleted_files_table_name
        
    elif status == HC.CONTENT_STATUS_PENDING:
        
        return pending_files_table_name
        
    else:
        
        return petitioned_files_table_name
        
    
class ClientDBFilesStorage( HydrusDBModule.HydrusDBModule ):
    
    def __init__( self, cursor: sqlite3.Cursor, modules_services: ClientDBServices.ClientDBMasterServices, modules_texts: ClientDBMaster.ClientDBMasterTexts ):
        
        self.modules_services = modules_services
        self.modules_texts = modules_texts
        
        HydrusDBModule.HydrusDBModule.__init__( self, 'client files storage', cursor )
        
    
    def _GetInitialIndexGenerationTuples( self ):
        
        index_generation_tuples = []
        
        return index_generation_tuples
        
    
    def AddFiles( self, service_id, insert_rows ):
        
        ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
        
        self._c.executemany( 'INSERT OR IGNORE INTO {} VALUES ( ?, ? );'.format( current_files_table_name ), ( ( hash_id, timestamp ) for ( hash_id, timestamp ) in insert_rows ) )
        
        self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( pending_files_table_name ), ( ( hash_id, ) for ( hash_id, timestamp ) in insert_rows ) )
        
        pending_changed = HydrusDB.GetRowCount( self._c ) > 0
        
        return pending_changed
        
    
    def ClearDeleteRecord( self, service_id, hash_ids ):
        
        deleted_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_DELETED )
        
        self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( deleted_files_table_name ), ( ( hash_id, ) for hash_id in hash_ids ) )
        
        num_deleted = HydrusDB.GetRowCount( self._c )
        
        return num_deleted
        
    
    def ClearLocalDeleteRecord( self, hash_ids = None ):
        
        # we delete from everywhere, but not for files currently in the trash
        
        service_ids_to_nums_cleared = {}
        
        local_non_trash_service_ids = self.modules_services.GetServiceIds( ( HC.COMBINED_LOCAL_FILE, HC.LOCAL_FILE_DOMAIN ) )
        
        if hash_ids is None:
            
            trash_current_files_table_name = GenerateFilesTableName( self.modules_services.trash_service_id, HC.CONTENT_STATUS_CURRENT )
            
            for service_id in local_non_trash_service_ids:
                
                deleted_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_DELETED )
                
                self._c.execute( 'DELETE FROM {} WHERE hash_id NOT IN ( SELECT hash_id FROM {} );'.format( deleted_files_table_name, trash_current_files_table_name ) )
                
                num_cleared = HydrusDB.GetRowCount( self._c )
                
                service_ids_to_nums_cleared[ service_id ] = num_cleared
                
            
            self._c.execute( 'DELETE FROM local_file_deletion_reasons WHERE hash_id NOT IN ( SELECT hash_id FROM {} );'.format( trash_current_files_table_name ) )
            
        else:
            
            trashed_hash_ids = self.FilterCurrentHashIds( self.modules_services.trash_service_id, hash_ids )
            
            ok_to_clear_hash_ids = set( hash_ids ).difference( trashed_hash_ids )
            
            if len( ok_to_clear_hash_ids ) > 0:
                
                for service_id in local_non_trash_service_ids:
                    
                    deleted_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_DELETED )
                    
                    self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( deleted_files_table_name ), ( ( hash_id, ) for hash_id in ok_to_clear_hash_ids ) )
                    
                    num_cleared = HydrusDB.GetRowCount( self._c )
                    
                    service_ids_to_nums_cleared[ service_id ] = num_cleared
                    
                
                self._c.executemany( 'DELETE FROM local_file_deletion_reasons WHERE hash_id = ?;', ( ( hash_id, ) for hash_id in ok_to_clear_hash_ids ) )
                
            
        
        return service_ids_to_nums_cleared
        
    
    def CreateInitialTables( self ):
        
        self._c.execute( 'CREATE TABLE local_file_deletion_reasons ( hash_id INTEGER PRIMARY KEY, reason_id INTEGER );' )
        
    
    def FilterAllCurrentHashIds( self, hash_ids, just_these_service_ids = None ):
        
        if just_these_service_ids is None:
            
            service_ids = self.modules_services.GetServiceIds( HC.SPECIFIC_FILE_SERVICES )
            
        else:
            
            service_ids = just_these_service_ids
            
        
        current_hash_ids = set()
        
        with HydrusDB.TemporaryIntegerTable( self._c, hash_ids, 'hash_id' ) as temp_hash_ids_table_name:
            
            for service_id in service_ids:
                
                current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
                
                hash_id_iterator = self._STI( self._c.execute( 'SELECT hash_id FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, current_files_table_name ) ) )
                
                current_hash_ids.update( hash_id_iterator )
                
            
        
        return current_hash_ids
        
    
    def FilterAllPendingHashIds( self, hash_ids, just_these_service_ids = None ):
        
        if just_these_service_ids is None:
            
            service_ids = self.modules_services.GetServiceIds( HC.SPECIFIC_FILE_SERVICES )
            
        else:
            
            service_ids = just_these_service_ids
            
        
        pending_hash_ids = set()
        
        with HydrusDB.TemporaryIntegerTable( self._c, hash_ids, 'hash_id' ) as temp_hash_ids_table_name:
            
            for service_id in service_ids:
                
                pending_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PENDING )
                
                hash_id_iterator = self._STI( self._c.execute( 'SELECT hash_id FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, pending_files_table_name ) ) )
                
                pending_hash_ids.update( hash_id_iterator )
                
            
        
        return pending_hash_ids
        
    
    def FilterCurrentHashIds( self, service_id, hash_ids ):
        
        if service_id == self.modules_services.combined_file_service_id:
            
            return set( hash_ids )
            
        
        with HydrusDB.TemporaryIntegerTable( self._c, hash_ids, 'hash_id' ) as temp_hash_ids_table_name:
            
            current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
            
            current_hash_ids = self._STS( self._c.execute( 'SELECT hash_id FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, current_files_table_name ) ) )
            
        
        return current_hash_ids
        
    
    def FilterPendingHashIds( self, service_id, hash_ids ):
        
        if service_id == self.modules_services.combined_file_service_id:
            
            return set( hash_ids )
            
        
        with HydrusDB.TemporaryIntegerTable( self._c, hash_ids, 'hash_id' ) as temp_hash_ids_table_name:
            
            pending_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PENDING )
            
            pending_hash_ids = self._STS( self._c.execute( 'SELECT hash_id FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, pending_files_table_name ) ) )
            
        
        return pending_hash_ids
        
    
    def DeletePending( self, service_id: int ):
        
        ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
        
        self._c.execute( 'DELETE FROM {};'.format( pending_files_table_name ) )
        self._c.execute( 'DELETE FROM {};'.format( petitioned_files_table_name ) )
        
    
    def DropFilesTables( self, service_id: int ):
        
        ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
        
        self._c.execute( 'DROP TABLE IF EXISTS {};'.format( current_files_table_name ) )
        self._c.execute( 'DROP TABLE IF EXISTS {};'.format( deleted_files_table_name ) )
        self._c.execute( 'DROP TABLE IF EXISTS {};'.format( pending_files_table_name ) )
        self._c.execute( 'DROP TABLE IF EXISTS {};'.format( petitioned_files_table_name ) )
        
    
    def GenerateFilesTables( self, service_id: int ):
        
        ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
        
        self._c.execute( 'CREATE TABLE IF NOT EXISTS {} ( hash_id INTEGER PRIMARY KEY, timestamp INTEGER );'.format( current_files_table_name ) )
        self._CreateIndex( current_files_table_name, [ 'timestamp' ] )
        
        self._c.execute( 'CREATE TABLE IF NOT EXISTS {} ( hash_id INTEGER PRIMARY KEY, timestamp INTEGER, original_timestamp INTEGER );'.format( deleted_files_table_name ) )
        self._CreateIndex( deleted_files_table_name, [ 'timestamp' ] )
        self._CreateIndex( deleted_files_table_name, [ 'original_timestamp' ] )
        
        self._c.execute( 'CREATE TABLE IF NOT EXISTS {} ( hash_id INTEGER PRIMARY KEY );'.format( pending_files_table_name ) )
        
        self._c.execute( 'CREATE TABLE IF NOT EXISTS {} ( hash_id INTEGER PRIMARY KEY, reason_id INTEGER );'.format( petitioned_files_table_name ) )
        self._CreateIndex( petitioned_files_table_name, [ 'reason_id' ] )
        
    
    def GetAPendingHashId( self, service_id ):
        
        pending_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PENDING )
        
        result = self._c.execute( 'SELECT hash_id FROM {};'.format( pending_files_table_name ) ).fetchone()
        
        if result is None:
            
            return None
            
        else:
            
            ( hash_id, ) = result
            
            return hash_id
            
        
    
    def GetAPetitionedHashId( self, service_id ):
        
        petitioned_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PETITIONED )
        
        result = self._c.execute( 'SELECT hash_id FROM {};'.format( petitioned_files_table_name ) ).fetchone()
        
        if result is None:
            
            return None
            
        else:
            
            ( hash_id, ) = result
            
            return hash_id
            
        
    
    def GetCurrentFilesCount( self, service_id, only_viewable = False ):
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        
        if only_viewable:
            
            # hashes to mimes
            result = self._c.execute( 'SELECT COUNT( * ) FROM {} CROSS JOIN files_info USING ( hash_id ) WHERE mime IN {};'.format( current_files_table_name, HydrusData.SplayListForDB( HC.SEARCHABLE_MIMES ) ) ).fetchone()
            
        else:
            
            result = self._c.execute( 'SELECT COUNT( * ) FROM {};'.format( current_files_table_name ) ).fetchone()
            
        
        ( count, ) = result
        
        return count
        
    
    def GetCurrentFilesInboxCount( self, service_id ):
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        
        result = self._c.execute( 'SELECT COUNT( * ) FROM {} CROSS JOIN file_inbox USING ( hash_id );'.format( current_files_table_name ) ).fetchone()
        
        ( count, ) = result
        
        return count
        
    
    def GetCurrentHashIdsList( self, service_id ):
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        
        hash_ids = self._STL( self._c.execute( 'SELECT hash_id FROM {};'.format( current_files_table_name ) ) )
        
        return hash_ids
        
    
    def GetCurrentFilesTotalSize( self, service_id ):
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        
        # hashes to size
        result = self._c.execute( 'SELECT SUM( size ) FROM {} CROSS JOIN files_info USING ( hash_id );'.format( current_files_table_name ) ).fetchone()
        
        ( count, ) = result
        
        return count
        
    
    def GetCurrentHashIdsToTimestamps( self, service_id, hash_ids ):
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        
        with HydrusDB.TemporaryIntegerTable( self._c, hash_ids, 'hash_id' ) as temp_hash_ids_table_name:
            
            rows = dict( self._c.execute( 'SELECT hash_id, timestamp FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, current_files_table_name ) ) )
            
        
        return rows
        
    
    def GetCurrentTableJoinPhrase( self, service_id, table_name ):
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        
        return '{} CROSS JOIN {} USING ( hash_id )'.format( table_name, current_files_table_name )
        
    
    def GetCurrentTimestamp( self, service_id: int, hash_id: int ):
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        
        result = self._c.execute( 'SELECT timestamp FROM {} WHERE hash_id = ?;'.format( current_files_table_name ), ( hash_id, ) ).fetchone()
        
        if result is None:
            
            return None
            
        else:
            
            ( timestamp, ) = result
            
            return timestamp
            
        
    
    def GetDeletedFilesCount( self, service_id: int ) -> int:
        
        deleted_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_DELETED )
        
        result = self._c.execute( 'SELECT COUNT( * ) FROM {};'.format( deleted_files_table_name ) ).fetchone()
        
        ( count, ) = result
        
        return count
        
    
    def GetDeletionStatus( self, service_id, hash_id ):
        
        # can have a value here and just be in trash, so we fetch it whatever the end result
        result = self._c.execute( 'SELECT reason_id FROM local_file_deletion_reasons WHERE hash_id = ?;', ( hash_id, ) ).fetchone()
        
        if result is None:
            
            file_deletion_reason = 'Unknown deletion reason.'
            
        else:
            
            ( reason_id, ) = result
            
            file_deletion_reason = self.modules_texts.GetText( reason_id )
            
        
        deleted_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_DELETED )
        
        is_deleted = False
        timestamp = None
        
        result = self._c.execute( 'SELECT timestamp FROM {} WHERE hash_id = ?;'.format( deleted_files_table_name ), ( hash_id, ) ).fetchone()
        
        if result is not None:
            
            is_deleted = True
            
            ( timestamp, ) = result
            
        
        return ( is_deleted, timestamp, file_deletion_reason )
        
    
    def GetExpectedTableNames( self ) -> typing.Collection[ str ]:
        
        expected_table_names = [
            'local_file_deletion_reasons',
        ]
        
        return expected_table_names
        
    
    def GetHashIdsToCurrentServiceIds( self, temp_hash_ids_table_name ):
        
        hash_ids_to_current_file_service_ids = collections.defaultdict( list )
        
        for service_id in self.modules_services.GetServiceIds( HC.SPECIFIC_FILE_SERVICES ):
            
            current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
            
            for hash_id in self._STI( self._c.execute( 'SELECT hash_id FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, current_files_table_name ) ) ):
                
                hash_ids_to_current_file_service_ids[ hash_id ].append( service_id )
                
            
        
        return hash_ids_to_current_file_service_ids
        
    
    def GetHashIdsToServiceInfoDicts( self, temp_hash_ids_table_name ):
        
        hash_ids_to_current_file_service_ids_and_timestamps = collections.defaultdict( list )
        hash_ids_to_deleted_file_service_ids_and_timestamps = collections.defaultdict( list )
        hash_ids_to_pending_file_service_ids = collections.defaultdict( list )
        hash_ids_to_petitioned_file_service_ids = collections.defaultdict( list )
        
        for service_id in self.modules_services.GetServiceIds( HC.SPECIFIC_FILE_SERVICES ):
            
            ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
            
            for ( hash_id, timestamp ) in self._c.execute( 'SELECT hash_id, timestamp FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, current_files_table_name ) ):
                
                hash_ids_to_current_file_service_ids_and_timestamps[ hash_id ].append( ( service_id, timestamp ) )
                
            
            for ( hash_id, timestamp, original_timestamp ) in self._c.execute( 'SELECT hash_id, timestamp, original_timestamp FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, deleted_files_table_name ) ):
                
                hash_ids_to_deleted_file_service_ids_and_timestamps[ hash_id ].append( ( service_id, timestamp, original_timestamp ) )
                
            
            for hash_id in self._c.execute( 'SELECT hash_id FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, pending_files_table_name ) ):
                
                hash_ids_to_pending_file_service_ids[ hash_id ].append( service_id )
                
            
            for hash_id in self._c.execute( 'SELECT hash_id FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, petitioned_files_table_name ) ):
                
                hash_ids_to_petitioned_file_service_ids[ hash_id ].append( service_id )
                
            
        
        return (
            hash_ids_to_current_file_service_ids_and_timestamps,
            hash_ids_to_deleted_file_service_ids_and_timestamps,
            hash_ids_to_pending_file_service_ids,
            hash_ids_to_petitioned_file_service_ids
        )
        
    
    def GetNumLocal( self, service_id: int ) -> int:
        
        current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
        combined_local_current_files_table_name = GenerateFilesTableName( self.modules_services.combined_local_file_service_id, HC.CONTENT_STATUS_CURRENT )
        
        ( num_local, ) = self._c.execute( 'SELECT COUNT( * ) FROM {} CROSS JOIN {} USING ( hash_id );'.format( current_files_table_name, combined_local_current_files_table_name ) ).fetchone()
        
        return num_local
        
    
    def GetPendingFilesCount( self, service_id: int ) -> int:
        
        pending_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PENDING )
        
        result = self._c.execute( 'SELECT COUNT( * ) FROM {};'.format( pending_files_table_name ) ).fetchone()
        
        ( count, ) = result
        
        return count
        
    
    def GetPetitionedFilesCount( self, service_id: int ) -> int:
        
        petitioned_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PETITIONED )
        
        result = self._c.execute( 'SELECT COUNT( * ) FROM {};'.format( petitioned_files_table_name ) ).fetchone()
        
        ( count, ) = result
        
        return count
        
    
    def GetServiceIdCounts( self, hash_ids ) -> typing.Dict[ int, int ]:
        
        with HydrusDB.TemporaryIntegerTable( self._c, hash_ids, 'hash_id' ) as temp_hash_ids_table_name:
            
            service_ids_to_counts = {}
            
            for service_id in self.modules_services.GetServiceIds( HC.SPECIFIC_FILE_SERVICES ):
                
                current_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_CURRENT )
                
                # temp hashes to files
                ( count, ) = self._c.execute( 'SELECT COUNT( * ) FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, current_files_table_name ) ).fetchone()
                
                service_ids_to_counts[ service_id ] = count
                
            
        
        return service_ids_to_counts
        
    
    def GetSomePetitionedRows( self, service_id: int ):
        
        petitioned_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PETITIONED )
        
        petitioned_rows = list( HydrusData.BuildKeyToListDict( self._c.execute( 'SELECT reason_id, hash_id FROM {} ORDER BY reason_id LIMIT 100;'.format( petitioned_files_table_name ) ) ).items() )
        
        return petitioned_rows
        
    
    def GetTablesAndColumnsThatUseDefinitions( self, content_type: int ) -> typing.List[ typing.Tuple[ str, str ] ]:
        
        tables_and_columns = []
        
        if HC.CONTENT_TYPE_HASH:
            
            for service_id in self.modules_services.GetServiceIds( HC.SPECIFIC_FILE_SERVICES ):
                
                ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
                
                tables_and_columns.extend( [
                    ( current_files_table_name, 'hash_id' ),
                    ( deleted_files_table_name, 'hash_id' ),
                    ( pending_files_table_name, 'hash_id' ),
                    ( petitioned_files_table_name, 'hash_id' )
                ] )
                
            
        
        return tables_and_columns
        
    
    def GetUndeleteRows( self, service_id, hash_ids ):
        
        deleted_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_DELETED )
        
        with HydrusDB.TemporaryIntegerTable( self._c, hash_ids, 'hash_id' ) as temp_hash_ids_table_name:
            
            rows = self._c.execute( 'SELECT hash_id, original_timestamp FROM {} CROSS JOIN {} USING ( hash_id );'.format( temp_hash_ids_table_name, deleted_files_table_name ) ).fetchall()
            
        
        return rows
        
    
    def PendFiles( self, service_id, hash_ids ):
        
        pending_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PENDING )
        
        self._c.executemany( 'INSERT OR IGNORE INTO {} ( hash_id ) VALUES ( ? );'.format( pending_files_table_name ), ( ( hash_id, ) for hash_id in hash_ids ) )
        
    
    def PetitionFiles( self, service_id, reason_id, hash_ids ):
        
        petitioned_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PETITIONED )
        
        self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( petitioned_files_table_name ), ( ( hash_id, ) for hash_id in hash_ids ) )
        
        self._c.executemany( 'INSERT OR IGNORE INTO {} ( hash_id, reason_id ) VALUES ( ?, ? );'.format( petitioned_files_table_name ), ( ( hash_id, reason_id ) for hash_id in hash_ids ) )
        
    
    def RecordDeleteFiles( self, service_id, insert_rows ):
        
        deleted_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_DELETED )
        
        now = HydrusData.GetNow()
        
        self._c.executemany(
            'INSERT OR IGNORE INTO {} ( hash_id, timestamp, original_timestamp ) VALUES ( ?, ?, ? );'.format( deleted_files_table_name ),
            ( ( hash_id, now, original_timestamp ) for ( hash_id, original_timestamp ) in insert_rows )
        )
        
        num_new_deleted_files = HydrusDB.GetRowCount( self._c )
        
        return num_new_deleted_files
        
    
    def RescindPendFiles( self, service_id, hash_ids ):
        
        pending_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PENDING )
        
        self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( pending_files_table_name ), ( ( hash_id, ) for hash_id in hash_ids ) )
        
    
    def RescindPetitionFiles( self, service_id, hash_ids ):
        
        petitioned_files_table_name = GenerateFilesTableName( service_id, HC.CONTENT_STATUS_PETITIONED )
        
        self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( petitioned_files_table_name ), ( ( hash_id, ) for hash_id in hash_ids ) )
        
    
    def RemoveFiles( self, service_id, hash_ids ):
        
        ( current_files_table_name, deleted_files_table_name, pending_files_table_name, petitioned_files_table_name ) = GenerateFilesTableNames( service_id )
        
        self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( current_files_table_name ), ( ( hash_id, ) for hash_id in hash_ids ) )
        
        self._c.executemany( 'DELETE FROM {} WHERE hash_id = ?;'.format( petitioned_files_table_name ), ( ( hash_id, ) for hash_id in hash_ids ) )
        
        pending_changed = HydrusDB.GetRowCount( self._c ) > 0
        
        return pending_changed
        
    
    def SetFileDeletionReason( self, hash_ids, reason ):
        
        reason_id = self.modules_texts.GetTextId( reason )
        
        self._c.executemany( 'REPLACE INTO local_file_deletion_reasons ( hash_id, reason_id ) VALUES ( ?, ? );', ( ( hash_id, reason_id ) for hash_id in hash_ids ) )
        
