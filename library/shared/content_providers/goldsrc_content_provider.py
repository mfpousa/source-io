from pathlib import Path
from typing import Iterator, Optional, Tuple, Union

from ...global_config import GoldSrcConfig
from ...goldsrc.wad import WadFile
from ...utils import Buffer
from .content_provider_base import ContentProviderBase


class GoldSrcContentProvider(ContentProviderBase):

    def __init__(self, filepath: Path):
        assert filepath.is_dir()
        super().__init__(filepath)

    def find_file(self, filepath: Union[str, Path], additional_dir=None, extension=None) -> Optional[Buffer]:
        if not GoldSrcConfig().use_hd and self.filepath.stem.endswith('_hd'):
            return None
        return self._find_file_generic(filepath, additional_dir, extension)

    def find_path(self, filepath: Union[str, Path], additional_dir=None, extension=None) -> Optional[Path]:
        return self._find_path_generic(filepath, additional_dir, extension)

    def glob(self, pattern: str) -> Iterator[tuple[Path, Buffer]]:
        yield from self._glob_generic(pattern)


class GoldSrcWADContentProvider(ContentProviderBase):

    def __init__(self, filepath: Path):
        assert filepath.suffix == '.wad'
        super().__init__(filepath)
        self.wad_file = WadFile(filepath)

    def find_file(self, filepath: Union[str, Path]) -> Optional[Buffer]:
        path = Path(filepath)
        if path.suffix.lower() in ('.vtf', '.vmt', '.mdl', '.phy', '.vtx', '.vvd', '.vvc', '.vmat', '.vtex', '.vmdl', '.vwrld', '.vcls', '.vphys', '.vpcf', '.vsnd', '.panm', '.vseq', '.vvis', '.vts'):
            return None
        return self.wad_file.get_file(path.stem)

    def find_path(self, filepath: Union[str, Path]) -> Optional[Path]:
        path = Path(filepath)
        if path.suffix.lower() in ('.vtf', '.vmt', '.mdl', '.phy', '.vtx', '.vvd', '.vvc', '.vmat', '.vtex', '.vmdl', '.vwrld', '.vcls', '.vphys', '.vpcf', '.vsnd', '.panm', '.vseq', '.vvis', '.vts'):
            return None
        entry = self.wad_file.get_file(path.stem)
        if entry:
            return Path(self.filepath.as_posix() + ":" + path.as_posix())

    def glob(self, pattern: str) -> Iterator[tuple[Path, Buffer]]:
        return iter([])
